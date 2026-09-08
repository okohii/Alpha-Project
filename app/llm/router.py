from __future__ import annotations

from enum import StrEnum
import httpx
import asyncio
import logging
from typing import Any

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.gemini import GeminiProvider, GeminiAPIError
from app.llm.mock import MockLLMProvider
from app.llm.ollama import OllamaProvider


class LLMRoute(StrEnum):
    local = "local"
    cloud = "cloud"
    auto = "auto"


class LLMRouter:
    def __init__(self, local_provider: LLMProvider | None = None, cloud_provider: LLMProvider | None = None) -> None:
        self.settings = get_settings()
        self.local_provider = local_provider or OllamaProvider()
        if cloud_provider is not None:
            self.cloud_provider = cloud_provider
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
        simple_markers = (
            "qual é",
            "qual e",
            "quem é",
            "quem e",
            "o que é",
            "o que e",
            "quanto custa",
            "como usar",
            "me diga",
            "resuma",
            "explica de forma simples",
        )
        lower = normalized.lower()
        return any(marker in lower for marker in simple_markers)

    def _internet_available(self) -> bool:
        if not self.settings.gemini_api_key:
            return False
        try:
            response = httpx.get("https://www.google.com", timeout=2.5)
            return response.is_success
        except Exception:
            return False

    def choose(self, question: str | None = None) -> LLMProvider:
        if question is None:
            return self.local_provider

        mode = self.settings.llm_mode
        cloud_available = self.settings.allow_cloud_llm and bool(self.settings.gemini_api_key)

        if mode == "cloud":
            if cloud_available and self._internet_available():
                return FaultTolerantProvider(local=self.local_provider, cloud=self.cloud_provider)
            return self.local_provider

        if mode == "auto":
            if cloud_available and self._internet_available() and not self._is_simple_question(question):
                return FaultTolerantProvider(local=self.local_provider, cloud=self.cloud_provider)
            return self.local_provider

        return self.local_provider

    def describe_current(self) -> dict[str, str | bool | list[str]]:
        provider = self.choose()
        payload: dict[str, str | bool | list[str]] = {
            "llm_mode": self.settings.llm_mode,
            "provider_name": provider.__class__.__name__,
            "allow_cloud_llm": self.settings.allow_cloud_llm,
            "allow_web": self.settings.allow_web,
            "allowed_directories": [str(path) for path in self.settings.allowed_directories],
        }
        if hasattr(provider, "model"):
            payload["model"] = str(getattr(provider, "model"))
        if hasattr(provider, "base_url"):
            payload["base_url"] = str(getattr(provider, "base_url"))
        return payload


class FaultTolerantProvider:
    """Wraps a cloud and local provider. Tries cloud with retries/backoff and falls back to local on errors.

    The wrapper retries only for transient HTTP errors (429, 500, 502, 503, 504) or network exceptions.
    Client errors (400, 401, 403) are re-raised immediately.
    """

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, local: LLMProvider, cloud: LLMProvider, max_retries: int = 2, base_backoff: float = 1.0) -> None:
        self.local = local
        self.cloud = cloud
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self._logger = logging.getLogger("app.llm.fallback")

    async def complete(self, messages: list[Any], tools: list[dict[str, Any]] | None = None, temperature: float = 0.2):
        last_exc: Exception | None = None
        for attempt in range(0, self.max_retries + 1):
            try:
                if attempt > 0:
                    backoff = self.base_backoff * (2 ** (attempt - 1))
                    self._logger.info("Retrying cloud provider (attempt %d) in %.1fs", attempt, backoff)
                    await asyncio.sleep(backoff)
                self._logger.debug("Attempting cloud provider (attempt %d)", attempt)
                return await self.cloud.complete(messages, tools=tools, temperature=temperature)
            except GeminiAPIError as exc:
                last_exc = exc
                # Only retry on retryable status codes
                if getattr(exc, "status_code", None) in self.RETRYABLE_STATUS:
                    self._logger.warning("Cloud provider transient error (status=%s) on attempt %d: %s", exc.status_code, attempt, exc)
                    continue
                # Non-retryable client error: re-raise immediately
                self._logger.error("Cloud provider returned non-retryable status=%s: %s", exc.status_code, exc)
                raise
            except Exception as exc:  # network-level or unexpected error — treat as retryable
                last_exc = exc
                self._logger.warning("Cloud provider failed on attempt %d: %s", attempt, exc)

        # If we get here, cloud failed repeatedly — fall back to local
        self._logger.error("Cloud provider unavailable after %d attempts; falling back to local. last_error=%s", self.max_retries, last_exc)
        try:
            return await self.local.complete(messages, tools=tools, temperature=temperature)
        except Exception as exc:  # pragma: no cover - local provider also failed
            self._logger.exception("Local provider also failed after cloud fallback: %s", exc)
            raise last_exc or exc
