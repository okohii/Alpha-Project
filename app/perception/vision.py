from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.evidence import Evidence, EvidenceKind, VerificationPolicy, VerificationResult, VerificationService
from app.perception.vision.verify import OllamaVisionVerifier, get_vision_verifier


@dataclass(slots=True)
class VisionPerceptor:
    """Perceptor de visão que produz evidência estruturada sem alegar sucesso."""

    _verifier: OllamaVisionVerifier | None = field(default=None, repr=False)

    def _ensure_verifier(self) -> OllamaVisionVerifier:
        if self._verifier is None:
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
        result = await verifier.verify(
            image_path, goal, max_retries=max_retries, retry_delay=retry_delay
        )
        achieved = result.get("achieved")
        confidence = result.get("confidence", 0.0)
        feedback = result.get("feedback", "")
        return Evidence(
            kind=EvidenceKind.SCREENSHOT,
            screenshot=image_path,
            ocr={
                "achieved": achieved,
                "confidence": confidence,
                "feedback": feedback,
            },
        )

    def perceive(
        self,
        image_path: str,
        goal: str,
        *,
        max_retries: int = 0,
        retry_delay: float = 2.0,
    ) -> Evidence:
        """Compatibilidade síncrona; não deve ser chamada de dentro do event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.aperceive(
                    image_path, goal, max_retries=max_retries, retry_delay=retry_delay
                )
            )
        raise RuntimeError("VisionPerceptor.perceive() cannot run inside an active event loop; use await aperceive().")

    async def averify_with_goal(
        self,
        image_path: str,
        goal: str,
        policy: VerificationPolicy | None = None,
    ) -> VerificationResult:
        evidence = await self.aperceive(image_path, goal)
        raw = evidence.ocr if isinstance(evidence.ocr, dict) else {}
        achieved = raw.get("achieved")
        confidence = float(raw.get("confidence", 0.0) or 0.0)
        if achieved is True and confidence >= 0.8:
            return VerificationResult.SUCCESS
        if achieved is False and confidence >= 0.8:
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
        raise RuntimeError("VisionPerceptor.verify_with_goal() cannot run inside an active event loop; use await averify_with_goal().")
