from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

from app.evidence import Evidence, EvidenceKind
from app.perception.accessibility import AccessibilityPerceptor, AccessibilityTree
from app.perception.dom import DOMPerceptor, DOMTree
from app.perception.ocr import OCRPerceptor, OCREvidence
from app.perception.vision import VisionPerceptor
from app.evidence import VerificationResult


@dataclass(slots=True)
class PerceptionResult:
    """Resultado do orchestrador de percepção."""

    kind: EvidenceKind
    evidence: Evidence
    source: str  # "accessibility", "dom", "ocr", "vision"
    confidence: float | None = None
    skipped_reason: str | None = None


@dataclass(slots=True)
class PerceptionOrchestrator:
    """Orquestrador hierárquico de percepção.

    Seleciona a melhor fonte de informação disponível na ordem:
    1. Árvore de acessibilidade (mais estruturada, mais barata)
    2. DOM (estruturado, disponível em navegadores/web apps)
    3. OCR (texto de captura, custo médio)
    4. Visão (último recurso, custo alto)

    A regra é: nunca pule um nível estruturado a menos que ele seja
    insuficiente (retorne None/indeterminado).
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
        """Executa a percepção na hierarquia e retorna o melhor resultado encontrado.

        Ordem de tentativa:
        1. Accessibility Tree
        2. DOM (se disponível)
        3. OCR (se houver image_path ou texto simulado)
        4. Visão (último recurso, com image_path e goal)
        """

        # 1. Accessibility Tree
        acc_result = self.accessibility.perceive(accessible_tree)
        if acc_result and acc_result.root.name:
            return PerceptionResult(
                kind=EvidenceKind.ACCESSIBILITY_TREE,
                evidence=acc_result,
                source="accessibility",
                confidence=1.0,
            )

        # 2. DOM
        dom_result = self.dom.perceive(dom_tree)
        if dom_result and dom.root is not None:
            # Verifica se há nós_changed ou conteúdo relevante
            if dom.root or dom.nodes:
                return PerceptionResult(
                    kind=EvidenceKind.DOM_STATE,
                    evidence=dom_result,
                    source="dom",
                    confidence=0.8,
                )

        # 3. OCR
        if image_path is not None or goal is not None:
            ocr_result = self.ocr.perceive(image_path=image_path)
            if ocr_result and ocr_result.result and ocr_result.result.text:
                return PerceptionResult(
                    kind=EvidenceKind.OCR,
                    evidence=ocr_result,
                    source="ocr",
                    confidence=ocr_result.result.confidence if ocr_result.result else None,
                )

        # 4. Visão (último recurso)
        if image_path is not None and goal is not None:
            vision_result = self.vision.perceive(image_path=image_path, goal=goal)
            if evidence:
                return PerceptionResult(
                    kind=EvidenceKind.VISION,
                    evidence=vision_result,
                    source="vision",
                    confidence=vision_result.evidence.tool_result.confidence if vision_result.evidence.tool_result else None,
                )

        # Nada encontrado
        return PerceptionResult(
            kind=EvidenceKind.UNCERTAIN,
            evidence=Evidence(kind=EvidenceKind.UNCERTAIN),
            source="none",
            skipped_reason="nenhuma fonte de percepção forneceu dados concretos",
        )

    def verify_action_with_policy(
        self,
        image_path: str | None = None,
        goal: str | None = None,
        action_name: str | None = None,
        policy: Any | None = None,
    ) -> VerificationResult:
        """Executa a percepção hierárquica e aplica verificação com política.

        Retorna VerificationResult (SUCCESS/FAILED/UNCERTAIN) considerando
        a política de verificação (mandatory/optional).
        """
        # 1. Perceber hierarquicamente
        result = self.perceive_hierarchical(
            accessible_tree=None,
            dom_tree=None,
            image_path=image_path,
            goal=goal,
        )

        # 2. Converter Evidence → VerificationResult via VerificationService
        service = VerificationService(policy)  # imported inline

        # Mapear o kind do Evidence para o tipo adequado
        kind = result.kind
        evidence = result.evidence

        # Casos baseados no kind
        if kind == EvidenceKind.VISION:
            # Já vem com verification result interna
            return service.verify_with_policy(evidence, action_name=action_name or "unknown")
        elif kind == EvidenceKind.TOOL_RESULT:
            return service.verify(evidence)
        elif kind == EvidenceKind.DOM_STATE:
            # DOM state verification: check changed nodes for success/failure indicators
            changed = evidence.changed_nodes if hasattr(evidence, "changed_nodes") else []
            if any(c.get("type") == "attributes" for c in changed):
                # Se mudanças de atributo indicam sucesso (ex.: disabled=False, visível=True)
                for c in changed:
                    if "before" in c and "after" in c:
                        after_val = c["after"].get("disabled")
                        if after_val is False:  # elemento habilitado/disabled removido/alterado
                            return VerificationResult.SUCCESS
                        if after_val is True:
                            return VerificationResult.FAILED
            # Se houve mudanças de visibilidade
            for c in changed:
                if c.get("type") == "visibility":
                    if after_val := c.get("after"):
                        return VerificationResult.SUCCESS if after_val else VerificationResult.FAILED
            # DOM state indeterminado
            return VerificationResult.UNCERTAIN
        elif kind == EvidenceKind.OCR:
            # OCR: se houver texto esperado, SUCCESS; senão, UNCERTAIN
            if evidence.result and evidence.result.text:
                return VerificationResult.SUCCESS
            return VerificationResult.UNCERTAIN
        elif kind == EvidenceKind.ACCESSIBILITY_TREE:
            # Árvore de acessibilidade: se há nome de elemento e estado visível, SUCCESS
            if evidence.root and evidence.root.name:
                return VerificationResult.SUCCESS
            return VerificationResult.UNCERTAIN
        else:
            # Nada concreto
            return VerificationResult.UNCERTAIN