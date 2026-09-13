from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class OCRResult:
    """Resultado do OCR extraído de uma captura de tela ou elemento."""

    text: str
    confidence: float
    bounding_box: dict[str, int] | None = None  # {left, top, width, height}
    page: int | None = None


@dataclass(slots=True)
class OCRResultPage:
    """Resultado do OCR de uma página completa."""

    page_number: int
    full_text: str
    lines: list[dict[str, Any]] | None = None
    success: bool = True


@dataclass(slots=True)
class OCRResultFull:
    """Resultado completo do OCR de uma captura."""

    overall_text: str
    pages: list[OCRResultPage] | None = None
    success: bool = True


@dataclass(slots=True)
class OCREvidence:
    """Evidence de OCR observada após uma ação ou captura."""

    kind: str = "ocr"
    result: OCRResult | OCRResultFull | None = None
    image_path: str | None = None
    success: bool = True


class OCRPerceptor:
    """Perceptor de OCR.

    OCR real (Tesseract/PaddleOCR) NÃO está implementado: ``available``
    é ``False`` por padrão. Sem motor real, NUNCA fazemos de conta que
    conseguimos extrair texto de uma imagem — a superfície é reduzida e o
    orquestrador ignora OCR quando indisponível.
    """

    available: bool = False

    def perceive(self, image_path: str | None = None, *, text: str | None = None) -> OCREvidence:
        """Percebe texto.

        Só produz evidência quando há TEXTO REAL fornecido pela fonte (ex.:
        DOM/acessibilidade) — nunca simula extração de uma imagem sem motor.
        """
        if not self.available and text is None:
            return OCREvidence(result=None, image_path=image_path, success=False)
        if text is not None:
            return OCREvidence(
                result=OCRResult(text=text, confidence=1.0),
                image_path=image_path,
                success=True,
            )
        return OCREvidence(result=None, image_path=image_path, success=False)

    def verify_action_text(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        action_name: str,
    ) -> dict[str, Any]:
        """Verifica se o texto esperado apareceu/após uma ação.

        Compara o texto antes e depois de uma ação (ex.: clicar em "Enviar")
        e retorna se o texto esperado foi encontrado.
        """
        found = False
        expected = action_name.lower()
        if after and isinstance(after, dict):
            after_text = after.get("text", "").lower()
            if expected in after_text:
                found = True
        if before and isinstance(before, dict):
            before_text = before.get("text", "").lower()
            # Se o texto já existia antes, verificar se mudou/acrescentou
            if expected not in before_text and found:
                found = True  # novo texto apareceu

        return {
            "action": action_name,
            "text_found": found,
            "expected": action_name,
            "after_text_snippet": after.get("text", "")[:100] if after else "",
            "before_text_snippet": before.get("text", "")[:100] if before else "",
        }