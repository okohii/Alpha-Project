from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


class DOMNodeDict(TypedDict):
    tag: str
    id: str | None
    class_name: str | None
    classes: list[str]
    attributes: dict[str, str]
    text_content: str
    inner_html: str | None
    xpath: str | None
    aria_role: str | None
    aria_attributes: dict[str, str]
    visible: bool
    focusable: bool
    rect: dict[str, int] | None


@dataclass(slots=True)
class DOMState:
    changed_nodes: list[DOMNodeDict] = field(default_factory=list)
    new_nodes: list[DOMNodeDict] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass(slots=True)
class DOMTree:
    root: DOMNodeDict | None = None
    nodes: list[DOMNodeDict] = field(default_factory=list)
    updated_at: float = field(default_factory=lambda: __import__("time").time())
    available: bool = True


class DOMPerceptor:
    """Perceptor de DOM sem fabricar estado quando não existe browser context."""

    def perceive(self, dom_tree: DOMTree | None = None) -> DOMTree:
        if dom_tree is not None:
            return dom_tree
        return DOMTree(root=None, nodes=[], available=False)

    def extract_node_info(self, node: DOMNodeDict) -> dict[str, Any]:
        return {"tag": node["tag"], "id": node["id"], "classes": node["classes"], "attributes": dict(node["attributes"]), "text_content": node["text_content"], "visible": node["visible"], "focusable": node["focusable"], "rect": node.get("rect")}

    def verify_interaction(self, before: DOMTree, after: DOMTree, action_name: str) -> dict[str, Any]:
        if not before.available or not after.available:
            return {"action": action_name, "verified": False, "changed_nodes": [], "summary": "DOM indisponível; nenhuma evidência inferida"}
        changes: list[dict[str, Any]] = []

        def key(node: DOMNodeDict) -> str:
            return node.get("id") or node.get("xpath") or f"{node.get('tag')}:{node.get('text_content', '')[:80]}"

        before_by_key = {key(node): node for node in before.nodes}
        after_by_key = {key(node): node for node in after.nodes}
        for node_key in set(before_by_key) | set(after_by_key):
            b = before_by_key.get(node_key)
            a = after_by_key.get(node_key)
            if b is None and a is not None:
                changes.append({"type": "new", "node": self.extract_node_info(a)})
                continue
            if a is None and b is not None:
                changes.append({"type": "removed", "id": node_key})
                continue
            assert b is not None and a is not None
            if b.get("attributes") != a.get("attributes"):
                changes.append({"type": "attributes", "id": node_key, "before": b.get("attributes"), "after": a.get("attributes")})
            if b.get("text_content") != a.get("text_content"):
                changes.append({"type": "text_content", "id": node_key, "before": b.get("text_content"), "after": a.get("text_content")})
            if b.get("visible") != a.get("visible"):
                changes.append({"type": "visibility", "id": node_key, "before": b.get("visible"), "after": a.get("visible")})
        return {"action": action_name, "verified": bool(changes), "changed_nodes": changes, "summary": self._make_summary(changes)}

    def _make_summary(self, changes: list[dict[str, Any]]) -> str:
        if not changes:
            return "nenhuma mudança observada"
        tipos = {c.get("type") for c in changes}
        if "new" in tipos and "removed" in tipos:
            return "nós inseridos e removidos"
        if "new" in tipos:
            return "nós novos inseridos"
        if "removed" in tipos:
            return "nós removidos"
        if "attributes" in tipos:
            return "atributos alterados"
        if "text_content" in tipos:
            return "texto alterado"
        return "mudanças observadas"
