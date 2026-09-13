from __future__ import annotations

import os
import platform
import sys
from typing import Any

from app.skills.computer.service import default_browser_progid
from app.tools.base import Tool, ToolPermission, ToolResult

_PROGID_TO_BROWSER: dict[str, str] = {
    "chromehtml": "chrome",
    "msedgehtm": "edge",
    "appxq0fevzme2pys62n3e0fbqa7peapykr8v": "edge",
    "firefoxurl-308046b0af4a39cb": "firefox",
    "bravehtml": "brave",
    "operastable": "opera",
    "vivaldihtm": "vivaldi",
    "zenbrowserhtml": "zen",
    "zenbrowserhtm": "zen",
}


def detect_default_browser() -> str | None:
    """Descobre o navegador padrão do sistema (registro Windows — fonte única)."""
    if os.name != "nt":
        return None
    progid = default_browser_progid()
    if not progid:
        return None
    return _PROGID_TO_BROWSER.get(progid.lower(), progid)


class SystemInfoTool(Tool):
    name = "system_info"
    description = (
        "Retorna informações básicas do sistema, incluindo o navegador padrão "
        "(use para responder qual é o navegador padrão do computador)."
    )
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "platform": platform.platform(),
                "python": sys.version,
                "machine": platform.machine(),
                "default_browser": detect_default_browser(),
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}