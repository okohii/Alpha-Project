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
        "Abre a pesquisa do Windows pelo menu Iniciar, digita uma consulta e, "
        "opcionalmente, confirma o primeiro resultado com Enter. Use para localizar "
        "aplicativos instalados, configurações ou arquivos pelo próprio Windows. "
        "Primeiro usa a tecla Windows isoladamente (mais compatível com Windows 10/11); "
        "Win+S fica como fallback. Não afirma que um aplicativo foi aberto sem evidência."
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
            # Em Windows 10/11, abrir o Start e começar a digitar é mais robusto
            # que depender do atalho Win+S, especialmente quando SearchHost está
            # sendo inicializado ou alguma política altera o comportamento do atalho.
            press_sequence("win")
            time.sleep(0.45)
            typed = type_text(query)
            time.sleep(max(0.35, float(kwargs.get("wait_seconds", 0.8))))

            enter = bool(kwargs.get("open_first", True))
            if enter:
                press_sequence("enter")
                time.sleep(0.8)

            foreground = _get_foreground_window_title()
            return ToolResult(
                name=self.name,
                success=True,
                data={
                    "query": query,
                    "typed_chars": typed,
                    "opened_first_result": enter,
                    "foreground": foreground,
                    "method": "start_menu_typing",
                    "note": "A consulta foi enviada ao menu Iniciar; confirme a janela/tela observada antes de afirmar o resultado.",
                },
            )
        except (OSError, RuntimeError, ValueError) as exc:
            # Fallback explícito para máquinas onde a tecla Windows isolada não
            # abriu o Start corretamente.
            try:
                press_sequence("win+s")
                time.sleep(0.5)
                typed = type_text(query)
                time.sleep(max(0.35, float(kwargs.get("wait_seconds", 0.8))))
                enter = bool(kwargs.get("open_first", True))
                if enter:
                    press_sequence("enter")
                    time.sleep(0.8)
                foreground = _get_foreground_window_title()
                return ToolResult(
                    name=self.name,
                    success=True,
                    data={
                        "query": query,
                        "typed_chars": typed,
                        "opened_first_result": enter,
                        "foreground": foreground,
                        "method": "win+s_fallback",
                        "note": "A consulta foi enviada via fallback Win+S; confirme a janela/tela observada antes de afirmar o resultado.",
                    },
                )
            except (OSError, RuntimeError, ValueError) as fallback_exc:
                return ToolResult(
                    name=self.name,
                    success=False,
                    data={"query": query},
                    error=f"Não consegui abrir a pesquisa do Windows: {fallback_exc}",
                )

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
