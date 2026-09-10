from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict

from app.llm.base import ExecutionEvidence


class DOMNodeDict(TypedDict):
    """Dicionário representation of a DOM node (flexível, sem dataclass slots)."""

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
    rect: dict[str, int] | None  # {left, top, width, height}


@dataclass(slots=True)
class DOMState:
    """Estado estruturado do DOM após uma ação."""

    changed_nodes: list[DOMNodeDict] = field(default_factory=list)
    new_nodes: list[DOMNodeDict] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)  # ids ou xpaths removidos
    summary: str = ""  # descrição textual resumida das mudanças


@dataclass(slots=True)
class DOMTree:
    """Árvore de DOM observada."""

    root: DOMNodeDict | None = None
    nodes: list[DOMNodeDict] = field(default_factory=list)
    updated_at: float = field(default_factory=lambda: __import__("time").time())


class DOMPerceptor:
    """Perceptor de DOM (Document Object Model).

    Extrai o estado estruturado do DOM após uma ação, permitindo
    verificar mudanças sem necessidade de visão quando o DOM está
    disponível (browser contexts, web apps).

    A prioridade é:
    1. Nó(s) que mudaram (mudança de atributo, texto, visibilidade)
    2. Nós novos inseridos
    3. Nós removidos
    3. Text content changes dos elementos visíveis
    4. Estrutura de atributos (id, class, aria-*, disabled, etc.)
    """

    def perceive(self, dom_tree: DOMTree | None = None) -> DOMTree:
        """Percebe o estado do DOM.

        Se nenhum árbol for fornecido, tenta extrair do ambiente corrente.
        """
        if dom_tree is not None:
            return dom_tree
        # Placeholder: retorna uma estrutura mínima
        root: DOMNodeDict = {
            "tag": "html",
            "id": None,
            "class_name": None,
            "classes": [],
            "attributes": {},
            "text_content": "",
            "inner_html": None,
            "xpath": None,
            "aria_role": None,
            "aria_attributes": {},
            "visible": True,
            "focusable": True,
            "rect": None,
        }
        tree = DOMTree(root=root)
        tree.nodes.append(root)
        return tree

    def extract_node_info(self, node: DOMNodeDict) -> dict[str, Any]:
        """Extrai informações relevantes de um nó DOM para dicionário."""
        return {
            "tag": node["tag"],
            "id": node["id"],
            "classes": node["classes"],
            "attributes": dict(node["attributes"]),
            "text_content": node["text_content"],
            "visible": node["visible"],
            "focusable": node["focusable"],
            "rect": node.get("rect"),
        }

    def verify_interaction(
        self,
        before: DOMTree,
        after: DOMTree,
        action_name: str,
    ) -> dict[str, Any]:
        """Compara DOM antes/depois de uma ação e retorna diferenças estruturadas."""
        changes: list[dict[str, Any]] = []

        # Coleta nós mudou (novo dicionário comparativo)
        def collect_changed(before_node: DOMNodeDict | None, after_node: DOMNodeDict | None) -> list[dict[str, Any]] | None:
            if before_node is None and after_node is None:
                return None
            if before_node is None:
                # Nó novo
                return [{"type": "new", "node": self.extract_node_info(after_node)}]
            if after_node is None:
                # Nó removido
                return [{"type": "removed", "id": after_node.get("id") if after_node else None}]
            # Ambos existem: comparar
            node_changes: list[dict[str, Any]] = []
            # Atributos que mudaram
            changed_attrs: dict[str, str] = {}
            for key in set(list(before_node["attributes"].keys()) + list(after_node["attributes"].keys())):
                bval = before_node["attributes"].get(key)
                aval = after_node["attributes"].get(key)
                if bval != aval:
                    changed_attrs[key] = {"before": bval, "after": aval}
            if changed_attrs:
                node_changes.append({"type": "attributes", "changed": changed_attrs})
            # Text content
            if before_node["text_content"] != after_node["text_content"]:
                node_changes.append({
                    "type": "text_content",
                    "before": before_node["text_content"],
                    "after": after_node["text_content"],
                })
            # Visibilidade
            if before_node["visible"] != after_node["visible"]:
                node_changes.append({
                    "type": "visibility",
                    "before": before_node["visible"],
                    "after": after_node["visible"],
                })
            # Rector
            if before_node.get("rect") != after_node.get("rect"):
                node_changes.append({
                    "type": "rect",
                    "before": before_node.get("rect"),
                    "after": after_node.get("rect"),
                })
            return node_changes if node_changes else None

        # Nó raiz
        if before.root is not None or after.root is not None:
            root_changes = collect_changed(before.root, after.root)
            if root_changes:
                changes.extend(root_changes)

        # Nós filhos (recursivo limitado a 1 nível profundo para performance)
        for before_child in (before.root.get("children") if hasattr(before.root, "children") else []) or []:
            for after_child in (after.root.get("children") if hasattr(after.root, "children") else []) or []:
                child_changes = collect_changed(before_child, after_child)
                if child_changes:
                    changes.extend(child_changes)

        return {
            "action": action_name,
            "changed_nodes": changes,
            "summary": self._make_summary(changes),
        }

    def _make_summary(self, changes: list[dict[str, Any]]) -> str:
        if not changes:
            return "nenhuma mudança observada"
        tipos = {c.get("type", "") for c in changes}
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