from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional

from app.core.events import EventType
from app.llm.base import ExecutionEvidence


class AccessibilityState(StrEnum):
    """Estados de acessibilidade observados em um elemento."""

    DISABLED = "disabled"
    ENABLED = "enabled"
    FOCUSED = "focused"
    ACTIVE = "active"
    VISIBLE = "visible"
    HIDDEN = "hidden"
    PRESSED = "pressed"
    CHECKED = "checked"
    INDETERMINATE = "indeterminate"
    REQUIRED = "required"
    SELECTED = "selected"


@dataclass(slots=True)
class AccessibilityNode:
    """Nodo da árvore de acessibilidade observado.

    Representa um elemento da UI com suas propriedades estruturais.
    """

    name: str
    role: str
    role_full: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    position: dict[str, int] | None = None  # {left, top, width, height}
    children: list["AccessibilityNode"] = field(default_factory=list)
    accessible: bool = True


@dataclass(slots=True)
class AccessibilityTree:
    """Arvore de acessibilidade completa observada.

    Raiz representa a janela/container principal.
    """

    root: AccessibilityNode
    updated_at: float = field(default_factory=lambda: __import__("time").time())


class AccessibilityPerceptor:
    """Perceptor de árvore de acessibilidade.

    Extrai o árbol de acessibilidade da interface gráfica de forma
    estruturada, nunca dependendo de OCR/vision para informações que
    podem ser obtidas deterministicamente.

    A prioridade é:
    1. Nome acessível (accessible name)
    2. Papel (role) e subtipo
    3. Estado (checked, focused, visible, etc.)
    4. Atributos (id, class, title, role, etc.)
    5. Relação posicional (bounds/rect)
    6. Relação de filhos/parentesco
    """

    def perceive(self, accessible_tree: AccessibilityTree | None = None) -> AccessibilityTree:
        """Percebe a árvore de acessibilidade.

        Se nenhum árbol for fornecido, tenta extrair do ambiente corrente.
        """
        # Placeholder: em um release futuro isso teria integração com
        # o API de acessibilidade do SO (MSAA/IA2/ATK). Por enquanto,
        # retorna uma árvore mínima.
        root = AccessibilityNode(
            name="",
            role="",
            state={},
            attributes={},
            accessible=True,
        )
        return AccessibilityTree(root=root)


    def extract_element(
        self,
        accessible_node: AccessibilityNode,
        *,
        include_attributes: bool = True,
        include_position: bool = True,
        include_children: bool = False,
    ) -> dict[str, Any]:
        """Extrai um dicionário resumido de um nodo da árvore.

        Útil para passar ao downstream (DOM perceptor, OCR, etc.).
        """
        data: dict[str, Any] = {
            "name": accessible_node.name,
            "role": accessible_node.role,
        }
        if include_attributes:
            data["attributes"] = accessible_node.attributes
        if include_position and accessible_node.position:
            data["position"] = accessible_node.position
        if include_children and accessible_node.children:
            data["children"] = [
                self.extract_element(c, include_attributes=False, include_position=False, include_children=False)
                for c in accessible_node.children
            ]
        return data


    def verify_interaction(
        self,
        before: AccessibilityTree,
        after: AccessibilityTree,
        action_name: str,
    ) -> dict[str, Any]:
        """Compara árvores antes/depois de uma ação e retorna diferenças.

        Útil para verificação de side-effects sem necessidade de visão.
        """
        diffs: list[dict[str, Any]] = []

        # Coleta de nós que mudaram de estado
        def find_diffs(before_node: AccessibilityNode, after_node: AccessibilityNode) -> list[dict[str, Any]]:
            changes: list[dict[str, Any]] = []
            # Diferenças de estado
            for state_key in set(list(before_node.state.keys()) + list(after_node.state.keys())):
                before_val = before_node.state.get(state_key)
                after_val = after_node.state.get(state_key)
                if before_val != after_val:
                    changes.append({
                        "state": state_key,
                        "before": before_val,
                        "after": after_val,
                    })
            # Diferenças de nome
            if before_node.name != after_node.name:
                changes.append({"field": "name", "before": before_node.name, "after": after_node.name})
            # Diferenças de atributos selecionados
            for key in set(list(before_node.attributes.keys()) + list(after_node.attributes.keys())):
                before_val = before_node.attributes.get(key)
                after_val = after_node.attributes.get(key)
                if before_val != after_val:
                    changes.append({"field": key, "before": before_val, "after": after_val})
            # Diferenças de filhos (contagem)
            if len(before_node.children) != len(after_node.children):
                changes.append({
                    "field": "children_count",
                    "before": len(before_node.children),
                    "after": len(after_node.children),
                })
            return changes

        diffs = find_diffs(before.root, after.root)
        return {
            "action": action_name,
            "differences": diffs,
            "before_state_summary": {
                "name": before.root.name,
                "role": before.root.role,
                "visible": before.root.state.get("visible"),
            },
            "after_state_summary": {
                "name": after.root.name,
                "role": after.root.role,
                "visible": after.root.state.get("visible"),
            },
        }