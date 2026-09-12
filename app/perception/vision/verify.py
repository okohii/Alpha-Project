"""Verificação visual conservadora pós-ação."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import get_settings


_MIN_VISUAL_CONFIDENCE = 0.80


def build_verify_prompt(goal: str) -> str:
    return (
        "Você é um auditor de automação de interface. Analise o screenshot e responda "
        "apenas com JSON válido e compacto.\n"
        "Campos: achieved (booleano, true somente se a meta estiver claramente visível), "
        "confidence (0 a 1), feedback (frase curta).\n"
        "Não transforme intenção em evidência; ausência de prova deve resultar em achieved=false.\n"
        f"Objetivo: {goal}"
    )


class OllamaVisionVerifier:
    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider

    def available(self) -> bool:
        if self.provider is None:
            return False
        try:
            return bool(self.provider.available())
        except Exception:
            return False

    async def verify(self, image_path: str, goal: str, max_retries: int = 0, retry_delay: float = 2.0) -> dict[str, Any]:
        attempts = 0
        details: list[dict[str, Any]] = []
        while True:
            attempt = await self._describe(image_path, goal)
            details.append(attempt)
            achieved = attempt.get("achieved")
            confidence = float(attempt.get("confidence", 0.0) or 0.0)
            # True só é aceito quando a confiança também passa o piso.
            if achieved is True and confidence >= _MIN_VISUAL_CONFIDENCE:
                return {"achieved": True, "confidence": confidence, "attempts": attempts + 1, "last": attempt, "details": details}
            if attempts >= max_retries:
                return {"achieved": False if achieved is False else None, "confidence": confidence, "attempts": attempts + 1, "last": attempt, "details": details}
            attempts += 1
            await asyncio.sleep(max(0.0, retry_delay))

    async def _describe(self, image_path: str, goal: str) -> dict[str, Any]:
        if not self.available():
            return {"achieved": None, "confidence": 0.0, "feedback": "sem visão disponível"}
        try:
            raw = await self.provider.describe(image_path, max_chars=2000, prompt=build_verify_prompt(goal))
        except Exception as exc:
            return {"achieved": None, "confidence": 0.0, "feedback": f"erro de visão: {exc}"}
        return _parse_verdict(raw)


def _find_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return ""


def _parse_verdict(raw: str) -> dict[str, Any]:
    candidate = _find_json_object(raw or "")
    parsed: dict[str, Any] = {}
    if candidate:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                parsed = value
        except json.JSONDecodeError:
            pass
    achieved = parsed.get("achieved")
    if isinstance(achieved, str):
        achieved = achieved.strip().lower() in ("true", "sim", "yes", "1", "ok")
    confidence = parsed.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "achieved": achieved if isinstance(achieved, bool) else None,
        "confidence": confidence,
        "feedback": str(parsed.get("feedback", "") or ""),
    }


def get_vision_verifier() -> OllamaVisionVerifier:
    settings = get_settings()
    if not settings.ollama_vision_model:
        return OllamaVisionVerifier(provider=None)
    from app.perception.vision import OllamaVisionProvider
    return OllamaVisionVerifier(provider=OllamaVisionProvider())
