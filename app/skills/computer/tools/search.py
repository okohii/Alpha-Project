"""Busca de aplicativos pelo menu Iniciar do Windows."""

from __future__ import annotations

import os
import time
from typing import Any

from app.skills.computer.tools.keyboard import _get_foreground_window_title, press_sequence, type_text
from app.tools.base import Tool, ToolPermission, ToolResult


class WindowsSearchTool(Tool):
    name = "windows_search"
    description = (
        "Abre a pesquisa do Windows pelo atalho Win+S, digita uma consulta e, "
        "opcionalmente, confirma o primeiro resultado com Enter. Use para localizar "
        "aplicativos instalados, configurações ou arquivos pelo próprio menu do Windows. "
        "Não afirma que um aplicativo foi aberto: o resultado informa apenas a janela ativa."
    )
    permission = ToolPermission.write

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", "") or "").strip()
        if not query:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Informe o que deve ser pesquisado no Windows.",
            )
        if os.name != "nt":
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="A pesquisa pelo menu Iniciar só é suportada no Windows.",
            )

        try:
            press_sequence("win+s")
            time.sleep(0.35)
            typed = type_text(query)
            time.sleep(max(0.2, float(kwargs.get("wait_seconds", 0.6))))
            enter = bool(kwargs.get("open_first", True))
            if enter:
                press_sequence("enter")
                time.sleep(0.6)
            foreground = _get_foreground_window_title()
            return ToolResult(
                name=self.name,
                success=True,
                data={
                    "query": query,
                    "typed_chars": typed,
                    "opened_first_result": enter,
                    "foreground": foreground,
                    "note": "A pesquisa foi executada; confirme a janela/tela observada antes de afirmar o resultado.",
                },
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Aplicativo, configuração, arquivo ou termo a pesquisar"},
                "open_first": {"type": "boolean", "description": "Pressiona Enter para abrir o primeiro resultado (padrão: true)"},
                "wait_seconds": {"type": "number", "description": "Tempo para aguardar os resultados antes do Enter"},
            },
            "required": ["query"],
        }
