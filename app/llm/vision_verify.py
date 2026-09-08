"""Verificação visual pós-ação.

Depois de realizar uma ação (clicar, digitar, abrir um app), este módulo tira
um screenshot e pergunta ao modelo de visão se o objetivo foi atingido. Se não
bateu de primeira, tiramos novas capturas em até `max_retries` tentativas —
é o que transforma o agente de "executor" em "agente que confere o próprio
trabalho". Tudo é opcional: sem visão disponível, verify() retorna inconclusive.
"""
from __future__ import annotations

import time
from typing import Any

from app.core.config import get_settings


def build_verify_prompt(goal: str) -> str:
    return (
        "Você é um auditor de automação de interface. Analise o screenshot da tela "
        "e responda apenas com um JSON válido e compacto, sem texto extra.\n"
        "Campos esperados:\n"
        "  - achieved: booleano (true se o objetivo abaixo claramente foi atingido na tela)\n"
        "  - confidence: número de 0 a 1\n"
        "  - feedback: frase curta explicando o que foi visto e, se não atingido, o que falta.\n"
        f"Objetivo da ação do assistente: {goal}"
    )


class OllamaVisionVerifier:
    """Verifica visualmente usando o provider de visão via prompt estruturado."""

    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider
        self._settings = None

    def available(self) -> bool:
        if self.provider is None:
            return False
        try:
            return bool(self.provider.available())
        except Exception:
            return False

    async def verify(
        self,
        image_path: str,
        goal: str,
        max_retries: int = 0,
        retry_delay: float = 2.0,
    ) -> dict[str, Any]:
        """Verifica o screenshot. Com max_retries>0, refaz capturas até bater."""
        attempts = 0
        details: list[dict[str, Any]] = []
        while True:
            attempt = await self._describe(image_path, goal)
            details.append(attempt)
            achieved = attempt.get("achieved")
            if achieved is not None:
                if achieved or attempts >= max_retries:
                    return {
                        "achieved": achieved,
                        "attempts": attempts + 1,
                        "last": attempt,
                        "details": details,
                    }
            elif attempts >= max_retries:
                # Inconclusivo (sem visão ou erro): reporta como está.
                return {
                    "achieved": None,
                    "attempts": attempts + 1,
                    "last": attempt,
                    "details": details,
                }
            attempts += 1
            if image_path is not None:
                time.sleep(retry_delay)

    async def _describe(self, image_path: str, goal: str) -> dict[str, Any]:
        if not self.available():
            return {"achieved": None, "confidence": 0.0, "feedback": "sem visão disponível"}
        try:
            raw = await self.provider.describe(
                image_path, max_chars=2000, prompt=build_verify_prompt(goal)
            )
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
    import json

    candidate = _find_json_object(raw or "")
    parsed: dict[str, Any] = {}
    if candidate:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            parsed = {}
    achieved = parsed.get("achieved")
    if isinstance(achieved, str):
        achieved = achieved.strip().lower() in ("true", "sim", "yes", "1", "ok")
    confidence = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence)
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
    from app.llm.vision import OllamaVisionProvider

    return OllamaVisionVerifier(provider=OllamaVisionProvider())