from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.evidence import Evidence, EvidenceKind, VerificationResult
from app.perception.vision.verify import OllamaVisionVerifier, get_vision_verifier


@dataclass(slots=True)
class VisionPerceptor:
    """Perceptor de visão (último recurso quando fontes estruturadas são insuficientes).

    Usa modelo de visão (ex.: Ollama) para analisar screenshots e determinar
    se o objetivo da ação foi atingido. Nunca é a primeira opção — só é acionada
    quando Accessibility Tree, DOM e OCR não fornecem evidência suficiente.

    Never invent coordinates. If vision returns coordinates, require sufficient
    confidence before using them.
    """

    _verifier: OllamaVisionVerifier | None = field(default=None, repr=False)

    def _ensure_verifier(self) -> OllamaVisionVerifier:
        if self._verifier is None:
            self._verifier = get_vision_verifier()
        return self._verifier

    def perceive(
        self,
        image_path: str,
        goal: str,
        *,
        max_retries: int = 0,
        retry_delay: float = 2.0,
    ) -> Evidence:
        """Percebe via visão.

        Tenta verificar se o objetivo foi atingido na captura de tela.
        Retorna Evidence com kind='vision' e os dados do verifier.

        A estratégia é:
        1. Chama verify() do OllamaVisionVerifier.
        2. Se achieved=True → SUCCESS com feedback.
        3. If achieved=False → FAILED com feedback.
        4. If inconclusive → UNCERTAIN.
        """
        verifier = self._ensure_verifier()
        result = asyncio.run(
            verifier.verify(image_path, goal, max_retries=max_retries, retry_delay=retry_delay)
        )
        achieved = result.get("achieved")
        confidence = result.get("confidence", 0.0)
        feedback = result.get("feedback", "")

        if achieved is True:
            return Evidence(
                kind=EvidenceKind.VISION,
                tool_result={
                    "achieved": True,
                    "confidence": confidence,
                    "feedback": feedback,
                },
                success=True,
            )
        elif achieved is False:
            return Evidence(
                kind=EvidenceKind.VISION,
                tool_result={
                    "achieved": False,
                    "confidence": confidence,
                    "feedback": feedback,
                },
                success=False,
            )
        else:
            # Inconclusivo — visão não conseguiu decidir
            return Evidence(
                kind=EvidenceKind.VISION,
                tool_result={
                    "achieved": None,
                    "confidence": confidence,
                    "feedback": feedback or "visão inconclusiva",
                },
                success=None,
            )

    def verify_with_goal(
        self,
        image_path: str,
        goal: str,
        policy: Any | None = None,
    ) -> VerificationResult:
        """Versão de alto nível que retorna VerificationResult em vez de Evidence.

        Integra com VerificationPolicy se fornecida.
        """
        evidence = self.perceive(image_path, goal)
        service = VerificationService(policy)
        return service.verify(evidence)