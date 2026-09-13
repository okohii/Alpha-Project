from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class ReminderDeleteTool(Tool):
    name = "reminder_delete"
    description = (
        "Apaga/exclui/remove/cancela um lembrete agendado. "
        "Informe reminder_id (obtido com reminder_list); se não souber o id, "
        "liste primeiro com reminder_list. Ex.: reminder_delete reminder_id='abc123'"
    )
    permission = ToolPermission.write

    def __init__(self, reminder_service: Any) -> None:
        self.reminder_service = reminder_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        reminder_id = str(kwargs.get("reminder_id", ""))
        if not reminder_id:
            return ToolResult(
                name=self.name, success=False, data={},
                error="Informe reminder_id (obtido com reminder_list)",
            )
        try:
            await self.reminder_service.delete_reminder(reminder_id)
            return ToolResult(
                name=self.name, success=True, data={"deleted": reminder_id}
            )
        except Exception as exc:
            return ToolResult(
                name=self.name, success=False, data={}, error=str(exc)
            )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "ID do lembrete (de reminder_list)",
                }
            },
            "required": ["reminder_id"],
        }