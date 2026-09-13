from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.gemini import GeminiAPIError, GeminiProvider
from app.llm.mock import MockLLMProvider
from app.llm.ollama import OllamaProvider
from app.llm.openai_compatible import OpenAICompatibleAPIError, OpenAICompatibleProvider

# ── disponibilidade do Ollama (fallback local condicional) ────────────────
# Cache curto: resultado OK vale ~5s, falha vale ~2s (para detectar rápido
# quando o Ollama voltar). http_status do /api/tags é o probe canônico.
_OLLAMA_HEALTH_CACHE: dict[str, tuple[float, bool]] = {}
_OLLAMA_HEALTH_OK_TTL = 5.0
_OLLAMA_HEALTH_FAIL_TTL = 2.0


async def ollama_available(base_url: str | None) -> bool:
    """Verifica se o Ollama responde em ``base_url`` (com cache curto)."""
    if not base_url:
        return False
    now = time.monotonic()
    cached = _OLLAMA_HEALTH_CACHE.get(base_url)
    if cached:
        ttl = _OLLAMA_HEALTH_OK_TTL if cached[1] else _OLLAMA_HEALTH_FAIL_TTL
        if now - cached[0] < ttl:
            return cached[1]
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
        ok = response.is_success
    except Exception:
        ok = False
    _OLLAMA_HEALTH_CACHE[base_url] = (now, ok)
    return ok


class LLMRoute(StrEnum):
    local = "local"
    cloud = "cloud"
    auto = "auto"
    hybrid = "hybrid"


@dataclass(slots=True)
class RouteDecision:
    """Resolução observável de rota do LLM para um turno.

    Distingue explicitamente:

    - ``configured_mode``: o que foi pedido na configuração (``LLM_MODE``);
    - ``effective_mode``: o modo de fato usado após checagem de disponibilidade;
    - ``selected_route``: ``local`` ou ``cloud`` — onde a PRIMEIRA chamada irá;
    - ``fallback_reason``: por que a rota escolhida difere do modo configurado
      (ex.: ``cloud_unavailable``, ``local_model_unavailable``).
    """

    configured_mode: str
    effective_mode: str
    selected_route: str
    provider: LLMProvider
    fallback_reason: str | None = None
    cloud_available: bool = False
    primary_model: str = ""
    fallback_model: str | None = None


class LLMRouter:
    """Central routing policy for ALPHA.

    In hybrid mode, deterministic signals select the gateway only when a task
    is materially more demanding than a short local interaction. No extra LLM
    call is made just to classify the task.

    The OpenAI-compatible endpoint is treated as a gateway, not as a vendor
    model. For 9Router, ``alpha`` is the gateway/combo profile and the router
    behind it remains responsible for selecting the actual upstream model.
    """

    _COMPLEX_PATTERNS = (
        r"\b(?:depois|em seguida|ent[aã]o)\b",
        r"\b(?:passo|etapa|primeiro.*depois)\b",
        r"\b(?:whatsapp|telegram|discord|email|e-mail)\b",
        r"\b(?:github|gitlab|site|navegador|chrome|browser|aba|p[aá]gina)\b",
        r"\b(?:clic|digita|escrev|copi|cola|envia|manda|abr[ae]|fecha|pesquis)\b",
        r"\b(?:arquivo|pasta|download|documento)\b.*\b(?:mova|copi|renome|crie|edite|procure)\b",
        r"\b(?:compare|analise|analis|investigue|pesquise|planeje|organize|resolv)\b",
    )

    def __init__(
        self,
        local_provider: LLMProvider | None = None,
        cloud_provider: LLMProvider | None = None,
    ) -> None:
        self.settings = get_settings()
        self._logger = logging.getLogger("app.llm.router")
        self.local_provider = local_provider or OllamaProvider()
        if cloud_provider is not None:
            self.cloud_provider = cloud_provider
        elif self.settings.cloud_llm_enabled and self.settings.cloud_llm_base_url:
            self.cloud_provider = OpenAICompatibleProvider()
        elif self.settings.gemini_api_key:
            self.cloud_provider = GeminiProvider()
        else:
            self.cloud_provider = MockLLMProvider()

        self._logger.info(
            "[LLM] local=%s cloud=%s gateway=%s mode=%s",
            self._provider_model(self.local_provider),
            self._provider_model(self.cloud_provider),
            getattr(self.cloud_provider, "base_url", "-"),
            self.settings.llm_mode,
        )

    @staticmethod
    def _provider_model(provider: Any) -> str:
        model = getattr(provider, "model", None)
        if model:
            return str(model)
        return provider.__class__.__name__

    def _is_simple_question(self, question: str | None) -> bool:
        if not question:
            return False
        normalized = question.strip()
        if not normalized:
            return False
        words = normalized.split()
        if len(words) <= 8:
            return True
        lower = normalized.lower()
        simple_markers = (
            "qual é", "qual e", "quem é", "quem e", "o que é", "o que e",
            "quanto custa", "como usar", "me diga", "resuma", "explica de forma simples",
        )
        return any(marker in lower for marker in simple_markers) and not self._is_complex_task(normalized)

    def _is_complex_task(self, question: str | None) -> bool:
        if not question:
            return False
        lower = question.strip().lower()
        if len(lower.split()) >= 24:
            return True
        return any(re.search(pattern, lower) for pattern in self._COMPLEX_PATTERNS)

    def _cloud_available(self) -> bool:
        if not self.settings.allow_cloud_llm:
            return False
        if isinstance(self.cloud_provider, MockLLMProvider):
            return False
        if isinstance(self.cloud_provider, OpenAICompatibleProvider):
            return self.settings.cloud_llm_enabled and bool(self.settings.cloud_llm_base_url)
        return bool(self.settings.gemini_api_key)

    def resolve_route(self, question: str | None = None) -> RouteDecision:
        """Resolve a rota efetiva para um turno com razão observável.

        A rota NUNCA é ``cloud`` sem motivo explícito: ``mode_cloud``,
        ``complex_task`` (auto/hybrid) — e sempre com fallback explícito
        quando o provedor primário falhar.
        """
        mode = str(self.settings.llm_mode).lower()
        cloud_available = self._cloud_available()
        complex_task = bool(question) and self._is_complex_task(question)

        def _provider_ftp(primary: LLMProvider, fallback: LLMProvider | None, selected: str, reason: str) -> LLMProvider:
            if fallback is None:
                return primary
            return FaultTolerantProvider(
                primary=primary,
                fallback=fallback,
                label=selected,
                fallback_label="local" if selected == "cloud" else "cloud",
                reason=reason,
            )

        if mode == "cloud":
            if cloud_available:
                decision = RouteDecision(
                    configured_mode="cloud",
                    effective_mode="cloud",
                    selected_route="cloud",
                    provider=_provider_ftp(self.cloud_provider, self.local_provider, "cloud", "mode_cloud"),
                    fallback_reason=None,
                    cloud_available=True,
                    primary_model=self._provider_model(self.cloud_provider),
                    fallback_model=self._provider_model(self.local_provider),
                )
            else:
                decision = RouteDecision(
                    configured_mode="cloud",
                    effective_mode="local",
                    selected_route="local",
                    provider=self.local_provider,
                    fallback_reason="cloud_unavailable",
                    cloud_available=False,
                    primary_model=self._provider_model(self.local_provider),
                )
            self._logger.info("[LLM ROUTER] route=%s reason=%s mode=%s model=%s configured_mode=cloud effective_mode=%s",
                             decision.selected_route, decision.fallback_reason or "mode_cloud", mode,
                             decision.primary_model, decision.effective_mode)
            return decision

        if mode in {"auto", "hybrid"}:
            if cloud_available and self.settings.hybrid_cloud_for_complex and complex_task:
                decision = RouteDecision(
                    configured_mode=mode,
                    effective_mode="cloud",
                    selected_route="cloud",
                    provider=_provider_ftp(self.cloud_provider, self.local_provider, "cloud", "complex_task"),
                    fallback_reason=None,
                    cloud_available=True,
                    primary_model=self._provider_model(self.cloud_provider),
                    fallback_model=self._provider_model(self.local_provider),
                )
                self._logger.info("[LLM ROUTER] route=cloud reason=complex_task mode=%s model=%s configured_mode=%s effective_mode=cloud",
                                  mode, decision.primary_model, mode)
                return decision
            reason = "simple_task" if not complex_task else "cloud_disabled_or_not_required"
            decision = RouteDecision(
                configured_mode=mode,
                effective_mode="local",
                selected_route="local",
                provider=_provider_ftp(self.local_provider, self.cloud_provider if cloud_available else None, "local", reason),
                fallback_reason=reason,
                cloud_available=cloud_available,
                primary_model=self._provider_model(self.local_provider),
                fallback_model=self._provider_model(self.cloud_provider) if cloud_available else None,
            )
            self._logger.info("[LLM ROUTER] route=local reason=%s mode=%s model=%s", reason, mode, decision.primary_model)
            return decision

        # modo local (default histórico do ALPHA)
        decision = RouteDecision(
            configured_mode="local",
            effective_mode="local",
            selected_route="local",
            provider=_provider_ftp(self.local_provider, self.cloud_provider if cloud_available else None, "local", "mode_local"),
            fallback_reason="mode_local",
            cloud_available=cloud_available,
            primary_model=self._provider_model(self.local_provider),
            fallback_model=self._provider_model(self.cloud_provider) if cloud_available else None,
        )
        self._logger.info("[LLM ROUTER] route=local reason=mode_local mode=%s model=%s cloud_available=%s",
                          mode, decision.primary_model, cloud_available)
        return decision

    def choose(self, question: str | None = None) -> LLMProvider:
        return self.resolve_route(question).provider

    def route_name(self, question: str | None = None) -> str:
        return self.resolve_route(question).selected_route

    def describe_current(self) -> dict[str, str | bool | list[str] | None]:
        decision = self.resolve_route()
        provider = decision.provider
        payload: dict[str, str | bool | list[str] | None] = {
            "llm_mode": self.settings.llm_mode,
            "configured_mode": decision.configured_mode,
            "effective_mode": decision.effective_mode,
            "selected_route": decision.selected_route,
            "fallback_reason": decision.fallback_reason,
            "provider_name": provider.__class__.__name__,
            "allow_cloud_llm": self.settings.allow_cloud_llm,
            "cloud_llm_enabled": self.settings.cloud_llm_enabled,
            "cloud_llm_base_url": self.settings.cloud_llm_base_url,
            "cloud_llm_model": self.settings.cloud_llm_model or "alpha",
            "cloud_available": self._cloud_available(),
            "allow_web": self.settings.allow_web,
            "allowed_directories": [str(path) for path in self.settings.allowed_directories],
        }
        model = getattr(provider, "model", None)
        if model is None and isinstance(provider, FaultTolerantProvider):
            model = getattr(provider.primary, "model", None)
        if model is not None:
            payload["model"] = str(model)
        base_url = getattr(provider, "base_url", None)
        if base_url is not None:
            payload["base_url"] = str(base_url)
        return payload


class _FallbackStreamedResponse:
    """Streaming tolerante a falhas (Fase 4.3).

    Delega ao ``stream_turn`` da rota primária; caso a primária falhe ANTES de
    emitir qualquer token, recai para ``fallback.complete`` (conteúdo integral
    emitido em chunks) — preserva a experiência de streaming mesmo com fallback.
    Exposição ``tool_calls``/``content`` compatível com o ``StreamedResponse``.
    """

    def __init__(
        self,
        primary_stream: Any,
        provider: FaultTolerantProvider,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        temperature: float,
    ) -> None:
        self._primary_stream = primary_stream
        self._provider = provider
        self._messages = messages
        self._tools = tools
        self._temperature = temperature
        self.content: str = ""
        self.tool_calls: list[Any] | None = None

    async def __aiter__(self) -> Any:
        emitted = False
        try:
            async for token in self._primary_stream:
                emitted = True
                self.content += token
                yield token
        except Exception as exc:
            if emitted:
                raise
            provider = self._provider
            if provider.fallback is None or not provider.settings_fallback_enabled():
                raise
            provider.last_route = provider.fallback_label
            provider.last_fallback_reason = f"{provider.label}_unavailable"
            provider._logger.warning(
                "[LLM ROUTER] stream fallback route=%s reason=%s_unavailable error=%s",
                provider.fallback_label,
                provider.label,
                exc,
            )
            response = await provider.fallback.complete(
                self._messages, tools=self._tools, temperature=self._temperature
            )
            content = response.content or ""
            self.tool_calls = response.tool_calls
            for index in range(0, len(content), 96):
                chunk = content[index : index + 96]
                self.content += chunk
                yield chunk


class FaultTolerantProvider:
    """Provedor tolerante a falhas com rota primária e rota de fallback.

    Trabalha em qualquer direção (cloud→local ou local→cloud) e expõe a rota
    efetivamente selecionada via ``route`` / ``last_route`` / ``last_fallback_reason``.
    ``local``/``cloud`` permanecem como atributos de compatibilidade para o Agent.

    O fallback NUNCA é silencioso: quando a rota primária falha, um log com
    ``fallback_reason=<route>_unavailable`` é emitido antes de tentar a rota
    alternativa. O número de retries é limitado.
    """

    RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider | None = None,
        label: str = "local",
        fallback_label: str | None = None,
        reason: str = "",
        max_retries: int = 1,
        base_backoff: float = 0.75,
        local: LLMProvider | None = None,
        cloud: LLMProvider | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.label = label
        self.fallback_label = fallback_label or ("local" if label == "cloud" else "cloud")
        self.reason = reason
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.last_route = label
        self.last_fallback_reason: str | None = None
        # Compatibilidade com o Agent (metadata/fallback inspecionáveis).
        self.local = local if local is not None else (primary if label == "local" else fallback)
        self.cloud = cloud if cloud is not None else (primary if label == "cloud" else fallback)
        self._logger = logging.getLogger("app.llm.fallback")
        self._last_exc: Exception | None = None

    @property
    def route(self) -> str:
        return self.last_route

    @property
    def supports_streaming(self) -> bool:
        """A rota primária consegue fazer streaming de tokens."""
        return callable(getattr(self.primary, "stream_turn", None))

    async def stream_turn(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> Any:
        """Streaming com tolerância a falhas (rota primária com fallback)."""
        primary_stream = getattr(self.primary, "stream_turn", None)
        if primary_stream is None:
            # Rota primária sem suporte a streaming: cai para o caminho
            # buffered (complete) — comportamento anterior preservado.
            return await self.complete(messages, tools=tools, temperature=temperature)
        self.last_route = self.label
        streamed = await primary_stream(messages, tools=tools, temperature=temperature)
        return _FallbackStreamedResponse(
            streamed, self, messages, tools, temperature
        )

    def settings_fallback_enabled(self) -> bool:
        return get_settings().hybrid_cloud_fallback

    async def complete(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ):
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt:
                    await asyncio.sleep(self.base_backoff * (2 ** (attempt - 1)))
                self._logger.info(
                    "[LLM ROUTER] attempt route=%s provider=%s attempt=%d",
                    self.label,
                    self.primary.__class__.__name__,
                    attempt + 1,
                )
                self.last_route = self.label
                return await self.primary.complete(messages, tools=tools, temperature=temperature)
            except (GeminiAPIError, OpenAICompatibleAPIError) as exc:
                last_exc = exc
                if getattr(exc, "status_code", None) not in self.RETRYABLE_STATUS:
                    raise
                self._logger.warning(
                    "Cloud transient error status=%s attempt=%d: %s", exc.status_code, attempt, exc
                )
            except Exception as exc:
                last_exc = exc
                self._logger.warning(
                    "Primary provider (%s) failed attempt=%d: %s", self.label, attempt, exc
                )

        if self.fallback is None or not self.settings_fallback_enabled():
            self._last_exc = last_exc
            raise last_exc or RuntimeError("LLM provider failed")

        # Fallback local é CONDICIONAL: só ocorre quando o Ollama está de pé.
        # Se o modelo local não estiver disponível, o erro da rota primária
        # é preservado (nunca mascarado por um fallback morto).
        if self.fallback_label == "local" and getattr(self.fallback, "base_url", None):
            if not await ollama_available(str(self.fallback.base_url)):
                self.last_route = self.label
                self.last_fallback_reason = "local_unavailable_ollama_down"
                self._logger.warning(
                    "[LLM ROUTER] fallback=local skipped reason=ollama_down final_route=%s final_error=%s",
                    self.label,
                    last_exc,
                )
                self._last_exc = last_exc
                raise last_exc or RuntimeError("LLM provider failed")

        self.last_route = self.fallback_label
        self.last_fallback_reason = f"{self.label}_unavailable"
        self._logger.warning(
            "[LLM ROUTER] route=%s fallback_reason=%s_unavailable fallback_route=%s model=%s",
            self.fallback_label,
            self.label,
            self.fallback_label,
            getattr(self.fallback, "model", self.fallback.__class__.__name__),
        )
        try:
            return await self.fallback.complete(messages, tools=tools, temperature=temperature)
        except Exception as exc:
            self._last_exc = last_exc
            raise last_exc or exc from exc
