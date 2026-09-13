from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AccessibilityState(StrEnum):
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
    name: str
    role: str
    role_full: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    position: dict[str, int] | None = None
    children: list[AccessibilityNode] = field(default_factory=list)
    accessible: bool = True


@dataclass(slots=True)
class AccessibilityTree:
    root: AccessibilityNode
    updated_at: float = field(default_factory=lambda: __import__("time").time())


class AccessibilityPerceptor:
    """Perceptor determinístico com backend Windows UIA quando disponível.

    Não inventa uma árvore quando o backend não está disponível: retorna uma
    raiz explicitamente marcada como indisponível, permitindo ao orquestrador
    usar DOM/OCR/Vision como fallback sem transformar ausência de percepção em
    evidência.
    """

    def perceive(self, accessible_tree: AccessibilityTree | None = None) -> AccessibilityTree:
        if accessible_tree is not None:
            return accessible_tree
        try:
            from app.skills.computer.tools.uia import available, read_ui_text
            if available():
                elements = read_ui_text(limit=200)
                children = [
                    AccessibilityNode(
                        name=str(item.get("name", "")),
                        role=str(item.get("control_type", "Control")),
                        role_full=str(item.get("control_type", "Control")),
                        state={"visible": True},
                        attributes={"window": str(item.get("window", ""))},
                        position={
                            "left": int(item.get("x", 0)),
                            "top": int(item.get("y", 0)),
                            "width": 0,
                            "height": 0,
                        },
                    )
                    for item in elements
                    if item.get("name")
                ]
                return AccessibilityTree(
                    root=AccessibilityNode(
                        name="desktop",
                        role="Desktop",
                        state={"visible": True},
                        children=children,
                    )
                )
        except Exception:
            pass
        return AccessibilityTree(
            root=AccessibilityNode(
                name="",
                role="",
                state={"available": False},
                attributes={"source": "unavailable"},
                accessible=False,
            )
        )

    def extract_element(self, accessible_node: AccessibilityNode, *, include_attributes: bool = True, include_position: bool = True, include_children: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {"name": accessible_node.name, "role": accessible_node.role, "state": dict(accessible_node.state)}
        if include_attributes:
            data["attributes"] = accessible_node.attributes
        if include_position and accessible_node.position:
            data["position"] = accessible_node.position
        if include_children and accessible_node.children:
            data["children"] = [self.extract_element(c, include_attributes=False, include_position=False, include_children=False) for c in accessible_node.children]
        return data

    def verify_interaction(self, before: AccessibilityTree, after: AccessibilityTree, action_name: str) -> dict[str, Any]:
        diffs: list[dict[str, Any]] = []

        def find_diffs(before_node: AccessibilityNode, after_node: AccessibilityNode) -> list[dict[str, Any]]:
            changes: list[dict[str, Any]] = []
            for state_key in set(before_node.state) | set(after_node.state):
                if before_node.state.get(state_key) != after_node.state.get(state_key):
                    changes.append({"state": state_key, "before": before_node.state.get(state_key), "after": after_node.state.get(state_key)})
            if before_node.name != after_node.name:
                changes.append({"field": "name", "before": before_node.name, "after": after_node.name})
            for key in set(before_node.attributes) | set(after_node.attributes):
                if before_node.attributes.get(key) != after_node.attributes.get(key):
                    changes.append({"field": key, "before": before_node.attributes.get(key), "after": after_node.attributes.get(key)})
            if len(before_node.children) != len(after_node.children):
                changes.append({"field": "children_count", "before": len(before_node.children), "after": len(after_node.children)})
            return changes

        diffs = find_diffs(before.root, after.root)
        return {"action": action_name, "differences": diffs, "before_state_summary": {"name": before.root.name, "role": before.root.role, "visible": before.root.state.get("visible")}, "after_state_summary": {"name": after.root.name, "role": after.root.role, "visible": after.root.state.get("visible")}}
