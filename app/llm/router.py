from __future__ import annotations

import asyncio
import logging
import re
from enum import StrEnum
from typing import Any

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.gemini import GeminiAPIError, GeminiProvider
from app.llm.mock import MockLLMProvider
from app.llm.ollama import OllamaProvider
from app.llm.openai_compatible import OpenAICompatibleAPIError, OpenAICompatibleProvider


class LLMRoute(StrEnum):
    local = "local"
    cloud = "cloud"
    auto = "auto"
    hybrid = "hybrid"


class LLMRouter:
    """Central routing policy for ALPHA.

    In hybrid mode, deterministic signals select the cloud only when a task is
    materially more demanding than a short local interaction. No extra LLM
    call is made just to classify the task.
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
        self.local_provider = local_provider or OllamaProvider()
        if cloud_provider is not None:
            self.cloud_provider = cloud_provider
        elif self.settings.cloud_llm_enabled and self.settings.cloud_llm_base_url and self.settings.cloud_llm_model:
            self.cloud_provider = OpenAICompatibleProvider()
        elif self.settings.gemini_api_key:
            self.cloud_provider = GeminiProvider()
        else:
            self.cloud_provider = MockLLMProvider()
        self._logger = logging.getLogger("app.llm.router")

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
            return self.settings.cloud_llm_enabled and bool(self.settings.cloud_llm_model)
        return bool(self.settings.gemini_api_key)

    def choose(self, question: str | None = None) -> LLMProvider:
        if question is None:
            return self.local_provider

        mode = self.settings.llm_mode
        cloud_available = self._cloud_available()

        if mode == "cloud":
            if cloud_available:
                return FaultTolerantProvider(local=self.local_provider, cloud=self.cloud_provider)
            return self.local_provider

        if mode in {"auto", "hybrid"}:
            if cloud_available and self.settings.hybrid_cloud_for_complex and self._is_complex_task(question):
                return FaultTolerantProvider(local=self.local_provider, cloud=self.cloud_provider)
            return self.local_provider

        return self.local_provider

    def route_name(self, question: str | None = None) -> str:
        provider = self.choose(question)
        if isinstance(provider, FaultTolerantProvider):
            return "cloud"
        return "local"

    def describe_current(self) -> dict[str, str | bool | list[str]]:
        provider = self.choose()
        payload: dict[str, str | bool | list[str]] = {
            "llm_mode": self.settings.llm_mode,
            "provider_name": provider.__class__.__name__,
            "allow_cloud_llm": self.settings.allow_cloud_llm,
            "cloud_llm_enabled": self.settings.cloud_llm_enabled,
            "allow_web": self.settings.allow_web,
            "allowed_directories": [str(path) for path in self.settings.allowed_directories],
        }
        if hasattr(provider, "model"):
            payload["model"] = str(provider.model)
        if hasattr(provider, "base_url"):
            payload["base_url"] = str(provider.base_url)
        return payload


class FaultTolerantProvider:
    RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

    def __init__(self, local: LLMProvider, cloud: LLMProvider, max_retries: int = 1, base_backoff: float = 0.75) -> None:
        self.local = local
        self.cloud = cloud
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self._logger = logging.getLogger("app.llm.fallback")

    async def complete(self, messages: list[Any], tools: list[dict[str, Any]] | None = None, temperature: float = 0.2):
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt:
                    await asyncio.sleep(self.base_backoff * (2 ** (attempt - 1)))
                return await self.cloud.complete(messages, tools=tools, temperature=temperature)
            except (GeminiAPIError, OpenAICompatibleAPIError) as exc:
                last_exc = exc
                if getattr(exc, "status_code", None) not in self.RETRYABLE_STATUS:
                    raise
                self._logger.warning("Cloud transient error status=%s attempt=%d: %s", exc.status_code, attempt, exc)
            except Exception as exc:
                last_exc = exc
                self._logger.warning("Cloud provider failed attempt=%d: %s", attempt, exc)

        if not self.settings_fallback_enabled():
            raise last_exc or RuntimeError("Cloud provider failed")

        try:
            self._logger.warning("Cloud unavailable; falling back to local provider")
            return await self.local.complete(messages, tools=tools, temperature=temperature)
        except Exception as exc:
            raise last_exc or exc from exc

    def settings_fallback_enabled(self) -> bool:
        return get_settings().hybrid_cloud_fallback
