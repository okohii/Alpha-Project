"""Orquestrador hierárquico de percepção — produz Evidence válida sempre."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.evidence import (
    Evidence,
    EvidenceKind,
    VerificationResult,
    VerificationService,
)
from app.perception.accessibility import AccessibilityPerceptor, AccessibilityTree
from app.perception.dom import DOMPerceptor, DOMTree
from app.perception.ocr import OCRPerceptor
from app.perception.vision import VisionPerceptor


@dataclass(slots=True)
class PerceptionResult:
    """Resultado do orchestr adjust de percepção."""

    kind: EvidenceKind
    evidence: Evidence
    source: str  # "accessibility", "dom", "ocr", "vision", "inference"
    confidence: float | None = None
    skipped_reason: str | None = None


@dataclass(slots=True)
class PerceptionOrchestrator:
    """Seleciona a melhor fonte de informação disponível.

    Ordem: accessibility → DOM → OCR (apenas se disponível) → nada.
    Visão é assíncrona e oferecida via ``aperceive_vision``; a percepção
    síncrona NUNCA fabrica sucesso a partir de OCR placeholder.
    """

    accessibility: AccessibilityPerceptor = field(default_factory=AccessibilityPerceptor)
    dom: DOMPerceptor = field(default_factory=DOMPerceptor)
    ocr: OCRPerceptor = field(default_factory=OCRPerceptor)
    vision: VisionPerceptor = field(default_factory=VisionPerceptor)

    def perceive_hierarchical(
        self,
        accessible_tree: AccessibilityTree | None = None,
        dom_tree: DOMTree | None = None,
        image_path: str | None = None,
        goal: str | None = None,
    ) -> PerceptionResult:
        # 1. Acessibilidade (barata e estruturada)
        try:
            acc = self.accessibility.perceive(accessible_tree) if accessible_tree else None
            if acc is not None and getattr(acc, "root", None) is not None and getattr(acc.root, "name", ""):
                return PerceptionResult(
                    kind=EvidenceKind.ACCESSIBILITY_TREE,
                    evidence=Evidence(
                        kind=EvidenceKind.ACCESSIBILITY_TREE,
                        source="accessibility",
                        target=goal or "",
                        details=getattr(acc, "to_dict", lambda: None)()
                        if hasattr(acc, "to_dict")
                        else None,
                    ),
                    source="accessibility",
                    confidence=1.0,
                )
        except Exception:
            pass

        # 2. DOM (estruturado)
        try:
            dom = self.dom.perceive(dom_tree) if dom_tree else None
            if dom is not None and getattr(dom, "root", None) is not None:
                return PerceptionResult(
                    kind=EvidenceKind.DOM_STATE,
                    evidence=Evidence(
                        kind=EvidenceKind.DOM_STATE,
                        source="dom",
                        target=goal or "",
                        dom_state=getattr(dom, "to_dict", lambda: None)()
                        if hasattr(dom, "to_dict")
                        else None,
                    ),
                    source="dom",
                    confidence=0.8,
                )
        except Exception:
            pass

        # 3. OCR — apenas quando realmente disponível (sem placeholder).
        if self.ocr.available and image_path is not None:
            ocr_evidence = self.ocr.perceive(image_path=image_path)
            if ocr_evidence and ocr_evidence.success and ocr_evidence.result is not None:
                text = getattr(ocr_evidence.result, "text", "")
                if text:
                    return PerceptionResult(
                        kind=EvidenceKind.OCR,
                        evidence=Evidence(
                            kind=EvidenceKind.OCR,
                            source="ocr",
                            target=goal or "",
                            ocr={"text": text},
                            success=True,
                            confidence=getattr(ocr_evidence.result, "confidence", None),
                        ),
                        source="ocr",
                        confidence=getattr(ocr_evidence.result, "confidence", None),
                    )

        # 4. Visão é assíncrona (aperceive_vision). Nenhum sucesso é fabricado
        #    neste caminho síncrono.
        # Nada concreto: evidência INFERENCE (suposição), nunca VERIFIED.
        return PerceptionResult(
            kind=EvidenceKind.INFERENCE,
            evidence=Evidence(
                kind=EvidenceKind.INFERENCE,
                source="none",
                target=goal or "",
                details={"skipped": "nenhuma fonte de percepção forneceu dados concretos"},
                success=None,
            ),
            source="inference",
            skipped_reason="nenhuma fonte de percepção forneceu dados concretos",
        )

    async def aperceive_vision(self, image_path: str, goal: str) -> PerceptionResult:
        """Percepção por visão (assíncrona, custo alto) — nunca em loop ativo via sync."""
        evidence = await self.vision.aperceive(image_path, goal)
        return PerceptionResult(
            kind=EvidenceKind.VISION,
            evidence=evidence,
            source="vision",
            confidence=evidence.confidence,
        )

    def verify_action_with_policy(
        self,
        image_path: str | None = None,
        goal: str | None = None,
        action_name: str | None = None,
        policy: Any | None = None,
    ) -> VerificationResult:
        """Aplica verificação conservadora: ausência de prova ≠ sucesso."""
        service = VerificationService()
        result = self.perceive_hierarchical(image_path=image_path, goal=goal)

        if result.kind is EvidenceKind.OCR or result.kind is EvidenceKind.DOM_STATE:
            # Structured sources verify only the observed property.
            verified = service.verify(result.evidence)
            if verified is VerificationResult.UNCERTAIN:
                return VerificationResult.UNCERTAIN
            return verified
        # Accessibility tree with a named root supports SUCCESS only when a
        # concrete accessibility_state evidence was produced; otherwise UNCERTAIN.
        if result.kind is EvidenceKind.ACCESSIBILITY_TREE:
            return VerificationResult.UNCERTAIN
        return VerificationResult.UNCERTAIN

    async def averify_vision(self, image_path: str, goal: str, policy: Any | None = None) -> VerificationResult:
        service = VerificationService(policy) if policy is not None else VerificationService()
        evidence = await self.vision.aperceive(image_path, goal)
        if evidence.success is True and (evidence.confidence or 0) >= 0.8:
            return VerificationResult.SUCCESS
        if evidence.success is False and (evidence.confidence or 0) >= 0.8:
            return VerificationResult.FAILED
        return service.verify(evidence)