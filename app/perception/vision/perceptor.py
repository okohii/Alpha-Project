"""Perceptor de visão que produz evidência estruturada sem alegar sucesso.

Async de ponta a ponta: inferência de visão (Ollama) roda fora do event loop
via httpx async. A evidência usa ``EvidenceKind.VISION`` com ``success``
(veredito da fonte) separado de ``verified``.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.evidence import (
    Evidence,
    EvidenceKind,
    VerificationPolicy,
    VerificationResult,
    VerificationService,
)


@dataclass(slots=True)
class VisionPerceptor:
    """Perceptor de visão (último recurso quando fontes estruturadas são insuficientes).

    Nunca chama ``asyncio.run`` dentro de fluxo async. Para uso fora de um
    loop, existe ``aperceive`` (recomendado) e ``perceive`` (compat síncrona,
    que falha explicitamente se chamada dentro de loop ativo).
    """

    _verifier: Any | None = field(default=None, repr=False)

    def _ensure_verifier(self):
        if self._verifier is None:
            from app.perception.vision import get_vision_verifier

            self._verifier = get_vision_verifier()
        return self._verifier

    async def aperceive(
        self,
        image_path: str,
        goal: str,
        *,
        max_retries: int = 0,
        retry_delay: float = 2.0,
    ) -> Evidence:
        verifier = self._ensure_verifier()
        if not verifier.available():
            return Evidence(
                kind=EvidenceKind.VISION,
                source="vision",
                target=goal,
                success=None,
                confidence=None,
                details={"feedback": "visão indisponível"},
            )
        result = await verifier.verify(
            image_path, goal, max_retries=max_retries, retry_delay=retry_delay
        )
        achieved = result.get("achieved")
        confidence = result.get("confidence", 0.0)
        feedback = result.get("feedback", "")
        return Evidence(
            kind=EvidenceKind.VISION,
            source="vision",
            target=goal,
            screenshot=image_path,
            success=achieved,
            confidence=float(confidence or 0.0),
            details={"feedback": feedback, "attempts": result.get("attempts")},
        )

    def perceive(
        self,
        image_path: str,
        goal: str,
        *,
        max_retries: int = 0,
        retry_delay: float = 2.0,
    ) -> Evidence:
        """Compatibilidade síncrona; NÃO deve ser chamada de dentro do event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.aperceive(
                    image_path, goal, max_retries=max_retries, retry_delay=retry_delay
                )
            )
        raise RuntimeError(
            "VisionPerceptor.perceive() cannot run inside an active event loop; use await aperceive()."
        )

    async def averify_with_goal(
        self,
        image_path: str,
        goal: str,
        policy: VerificationPolicy | None = None,
    ) -> VerificationResult:
        evidence = await self.aperceive(image_path, goal)
        if evidence.success is True and (evidence.confidence or 0) >= 0.8:
            return VerificationResult.SUCCESS
        if evidence.success is False and (evidence.confidence or 0) >= 0.8:
            return VerificationResult.FAILED
        return VerificationService(policy).verify(evidence)

    def verify_with_goal(
        self,
        image_path: str,
        goal: str,
        policy: Any | None = None,
    ) -> VerificationResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.averify_with_goal(image_path, goal, policy))
        raise RuntimeError(
            "VisionPerceptor.verify_with_goal() cannot run inside an active event loop; "
            "use await averify_with_goal()."
        )


__all__ = ["VisionPerceptor"]