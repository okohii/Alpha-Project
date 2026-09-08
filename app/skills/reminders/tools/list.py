from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class ReminderListTool(Tool):
    name = "reminder_list"
    description = "Lista os lembretes agendados"
    permission = ToolPermission.read

    def __init__(self, reminder_service: Any) -> None:
        self.reminder_service = reminder_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        reminders = await self.reminder_service.list_reminders(
            limit=int(kwargs.get("limit", 100))
        )
        return ToolResult(
            name=self.name,
            success=True,
            data={"reminders": [view.to_dict() for view in reminders]},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        }