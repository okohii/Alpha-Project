from __future__ import annotations

import platform
import sys
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class SystemInfoTool(Tool):
    name = "system_info"
    description = "Retorna informações básicas do sistema"
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "platform": platform.platform(),
                "python": sys.version,
                "machine": platform.machine(),
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}