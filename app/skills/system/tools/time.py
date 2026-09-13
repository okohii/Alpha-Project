from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult

# Fuso horário do usuário: UTC-3 (Brasília)
USER_TIMEZONE = timezone(timedelta(hours=-3))


class TimeTool(Tool):
    name = "time"
    description = "Retorna a hora atual no fuso horário do usuário (UTC-3, Brasília)"
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        now = datetime.now(UTC)
        local_time = now.astimezone(USER_TIMEZONE)
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "utc": now.isoformat(),
                "local": local_time.isoformat(),
                "timezone": "UTC-3 (Brasília)",
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}
