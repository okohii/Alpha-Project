"""Provedor de visão local (Ollama) para descrever capturas de tela em texto."""
from __future__ import annotations
from dataclasses import dataclass, field

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
        self._logger = logging.getLogger("app.perception.vision")

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

@dataclass(slots=True)
class VisionPerceptor:
    """Perceptor de visão (último recurso quando fontes estruturadas são insuficientes)."""
    _verifier: Any | None = field(default=None, repr=False)
    
    def _ensure_verifier(self) -> OllamaVisionVerifier:
        if self._verifier is None:
            from app.perception.vision import get_vision_verifier
            self._verifier = get_vision_verifier()
        return self._verifier
    
    def perceive(self, image_path: str, goal: str, *,
                 max_retries: int = 0, retry_delay: float = 2.0) -> Evidence:
        verifier = self._ensure_verifier()
        result = asyncio.run(
            verifier.verify(image_path, goal, max_retries=max_retries, retry_delay=retry_delay)
        )
        achieved = result.get('achieved')
        confidence = result.get('confidence', 0.0)
        feedback = result.get('feedback', '')
        if achieved is True:
            return Evidence(
                kind=EvidenceKind.VISION,
                tool_result={'achieved': True, 'confidence': confidence, 'feedback': feedback},
                success=True,
            )
        elif achieved is False:
            return Evidence(
                kind=EvidenceKind.VISION,
                tool_result={'achieved': False, 'confidence': confidence, 'feedback': feedback},
                success=False,
            )
        else:
            return Evidence(
                kind=EvidenceKind.VISION,
                tool_result={'achieved': None, 'confidence': confidence, 'feedback': feedback or 'visão inconclusiva'},
                success=None,
            )
