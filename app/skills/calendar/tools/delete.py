from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class CalendarDeleteTool(Tool):
    name = "calendar_delete"
    description = "Remove um evento da agenda pelo identificador"
    permission = ToolPermission.write

    def __init__(self, calendar_service: Any) -> None:
        self.calendar_service = calendar_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        event_id = str(kwargs.get("event_id", ""))
        await self.calendar_service.delete_event(event_id)
        return ToolResult(name=self.name, success=True, data={"deleted": event_id})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"event_id": {"type": "string"}},
            "required": ["event_id"],
        }