"""Orquestrador hierárquico de percepção — produz Evidence válida sempre."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.evidence import Evidence, EvidenceKind, VerificationResult, VerificationService
from app.perception.accessibility import AccessibilityPerceptor, AccessibilityTree
from app.perception.dom import DOMPerceptor, DOMTree
from app.perception.ocr import OCRPerceptor
from app.perception.vision import VisionPerceptor


@dataclass(slots=True)
class PerceptionResult:
    kind: EvidenceKind
    evidence: Evidence
    source: str
    confidence: float | None = None
    skipped_reason: str | None = None


@dataclass(slots=True)
class PerceptionOrchestrator:
    """Seleciona a fonte de percepção mais determinística disponível.

    Ordem: accessibility → DOM → OCR → Vision. Fontes indisponíveis nunca são
    convertidas em sucesso por inferência.
    """

    accessibility: AccessibilityPerceptor = field(default_factory=AccessibilityPerceptor)
    dom: DOMPerceptor = field(default_factory=DOMPerceptor)
    ocr: OCRPerceptor = field(default_factory=OCRPerceptor)
    vision: VisionPerceptor = field(default_factory=VisionPerceptor)

    def perceive_hierarchical(self, accessible_tree: AccessibilityTree | None = None, dom_tree: DOMTree | None = None, image_path: str | None = None, goal: str | None = None) -> PerceptionResult:
        try:
            acc = self.accessibility.perceive(accessible_tree) if accessible_tree else None
            if acc is not None and getattr(acc, "root", None) is not None and getattr(acc.root, "name", ""):
                return PerceptionResult(EvidenceKind.ACCESSIBILITY_TREE, Evidence(kind=EvidenceKind.ACCESSIBILITY_TREE, source="accessibility", target=goal or "", details=getattr(acc, "to_dict", lambda: None)()), "accessibility", 1.0)
        except Exception:
            pass
        try:
            dom = self.dom.perceive(dom_tree) if dom_tree else None
            if dom is not None and getattr(dom, "root", None) is not None:
                return PerceptionResult(EvidenceKind.DOM_STATE, Evidence(kind=EvidenceKind.DOM_STATE, source="dom", target=goal or "", dom_state=getattr(dom, "to_dict", lambda: None)()), "dom", 0.8)
        except Exception:
            pass
        if self.ocr.available and image_path is not None:
            ocr_evidence = self.ocr.perceive(image_path=image_path)
            if ocr_evidence.success and ocr_evidence.result is not None:
                result = ocr_evidence.result
                text = getattr(result, "overall_text", "") or getattr(result, "text", "")
                if text:
                    confidence = getattr(result, "confidence", None)
                    if confidence is None:
                        lines = getattr(getattr(result, "pages", None) or [None], "__iter__", lambda: iter(()))()
                        confidences = [item.get("confidence", 0.0) for page in lines if page for item in (getattr(page, "lines", None) or [])]
                        confidence = sum(confidences) / len(confidences) if confidences else None
                    return PerceptionResult(EvidenceKind.OCR, Evidence(kind=EvidenceKind.OCR, source="ocr", target=goal or "", ocr={"text": text}, success=True, confidence=confidence), "ocr", confidence)
        return PerceptionResult(EvidenceKind.INFERENCE, Evidence(kind=EvidenceKind.INFERENCE, source="none", target=goal or "", details={"skipped": "nenhuma fonte de percepção forneceu dados concretos"}, success=None), "inference", None, "nenhuma fonte de percepção forneceu dados concretos")

    async def aperceive_browser_dom(self, browser: Any, *, limit: int = 500) -> PerceptionResult:
        dom = await self.dom.perceive_from_browser(browser, limit=limit)
        if not dom.available or dom.root is None:
            return PerceptionResult(EvidenceKind.INFERENCE, Evidence(kind=EvidenceKind.INFERENCE, source="dom", target="", details={"skipped": "contexto CDP/DOM indisponível"}, success=None), "inference", None, "contexto CDP/DOM indisponível")
        return PerceptionResult(EvidenceKind.DOM_STATE, Evidence(kind=EvidenceKind.DOM_STATE, source="dom", target="", dom_state={"nodes": dom.nodes, "updated_at": dom.updated_at}, success=True, confidence=0.9), "dom", 0.9)

    async def aperceive_vision(self, image_path: str, goal: str) -> PerceptionResult:
        evidence = await self.vision.aperceive(image_path, goal)
        return PerceptionResult(EvidenceKind.VISION, evidence, "vision", evidence.confidence)

    def verify_action_with_policy(self, image_path: str | None = None, goal: str | None = None, action_name: str | None = None, policy: Any | None = None) -> VerificationResult:
        service = VerificationService()
        result = self.perceive_hierarchical(image_path=image_path, goal=goal)
        if result.kind in {EvidenceKind.OCR, EvidenceKind.DOM_STATE}:
            return service.verify(result.evidence)
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
