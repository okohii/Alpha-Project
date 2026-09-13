"""Busca de aplicativos pelo menu Iniciar do Windows."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from app.skills.computer.tools.keyboard import (
    _get_foreground_window_title,
    press_sequence,
    type_text,
)
from app.tools.base import Tool, ToolPermission, ToolResult


def _run_search_sync(query: str, open_first: bool, wait_seconds: float) -> tuple[bool, dict[str, Any], str | None]:
    """Executa a busca (bloqueante) fora do event loop."""
    try:
        # Win+S abre a Pesquisa do Windows (overlay) — primário. Em máquinas
        # onde o atalho não responde, o fallback abre o Start isolado.
        press_sequence("win+s")
        time.sleep(0.45)
        typed = type_text(query)
        time.sleep(max(0.35, float(wait_seconds)))

        if open_first:
            press_sequence("enter")
            time.sleep(0.8)

        foreground = _get_foreground_window_title()
        return True, {
            "query": query,
            "typed_chars": typed,
            "opened_first_result": open_first,
            "foreground": foreground,
            "method": "start_menu_typing",
            "note": "A consulta foi enviada ao menu Iniciar; confirme a janela/tela observada antes de afirmar o resultado.",
        }, None
    except (OSError, RuntimeError, ValueError):
        # Fallback explícito para máquinas onde o atalho Win+S não respondeu.
        try:
            press_sequence("win")
            time.sleep(0.5)
            typed = type_text(query)
            time.sleep(max(0.35, float(wait_seconds)))
            if open_first:
                press_sequence("enter")
                time.sleep(0.8)
            foreground = _get_foreground_window_title()
            return True, {
                "query": query,
                "typed_chars": typed,
                "opened_first_result": open_first,
                "foreground": foreground,
                "method": "win+s_fallback",
                "note": "A consulta foi enviada via fallback Win+S; confirme a janela/tela observada antes de afirmar o resultado.",
            }, None
        except (OSError, RuntimeError, ValueError) as fallback_exc:
            return False, {"query": query}, str(fallback_exc)


class WindowsSearchTool(Tool):
    name = "windows_search"
    description = (
        "Abre a pesquisa do Windows pelo menu Iniciar, digita uma consulta e, "
        "opcionalmente, confirma o primeiro resultado com Enter. Use para localizar "
        "aplicativos instalados, configurações ou arquivos pelo próprio Windows. "
        "Abre a Pesquisa (Win+S) e, como fallback, o menu Iniciar isolado. "
        "Não afirma que um aplicativo foi aberto sem evidência."
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

        open_first = bool(kwargs.get("open_first", True))
        wait_seconds = float(kwargs.get("wait_seconds", 0.8))
        # Ações de teclado + waits bloqueantes saem do event loop (P-3).
        ok, data, error = await asyncio.to_thread(
            _run_search_sync, query, open_first, wait_seconds
        )
        if not ok:
            return ToolResult(
                name=self.name,
                success=False,
                data={"query": query},
                error=f"Não consegui abrir a pesquisa do Windows: {error}",
            )
        return ToolResult(name=self.name, success=True, data=data)

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
