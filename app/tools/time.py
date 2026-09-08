from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class TimeTool(Tool):
    name = "time"
    description = "Retorna a hora atual em UTC"
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        now = datetime.now(timezone.utc)
        return ToolResult(name=self.name, success=True, data={"utc": now.isoformat()})

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}
