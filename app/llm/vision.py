"""Provedor de visão local (Ollama) para descrever capturas de tela em texto."""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

DEFAULT_VISION_PROMPT = (
    "Você analisa capturas de tela de um PC Windows em português. "
    "Descreva de forma objetiva: (1) qual aplicativo/janela está em foco; "
    "(2) os elementos e botões interativos visíveis, indicando a coordenada "
    "aproximada em pixels de cada um no formato 'nome: (x, y)'; "
    "(3) mensagens/destaques relevantes. Não invente coords que não vê."
)


class OllamaVisionError(RuntimeError):
    pass


class OllamaVisionProvider:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_vision_model
        self.timeout = settings.llm_timeout_seconds
        self._logger = logging.getLogger("app.llm.vision")

    def available(self) -> bool:
        return bool(self.model)

    async def describe(
        self,
        image_path: str,
        prompt: str = DEFAULT_VISION_PROMPT,
        max_chars: int = 2000,
    ) -> str:
        if not self.model:
            raise OllamaVisionError("OLLAMA_VISION_MODEL não configurado")
        image = Path(image_path)
        if not image.exists():
            raise OllamaVisionError(f"Imagem não encontrada: {image_path}")
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt, "images": [encoded]},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        content = (data.get("message", {}) or {}).get("content", "")
        description = content.strip()
        return description[:max_chars] if max_chars else description