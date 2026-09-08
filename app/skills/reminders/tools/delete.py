from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class ReminderDeleteTool(Tool):
    name = "reminder_delete"
    description = "Remove um lembrete agendado pelo identificador"
    permission = ToolPermission.write

    def __init__(self, reminder_service: Any) -> None:
        self.reminder_service = reminder_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        reminder_id = str(kwargs.get("reminder_id", ""))
        await self.reminder_service.delete_reminder(reminder_id)
        return ToolResult(name=self.name, success=True, data={"deleted": reminder_id})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"reminder_id": {"type": "string"}},
            "required": ["reminder_id"],
        }