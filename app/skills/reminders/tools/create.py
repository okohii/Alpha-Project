from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class ReminderCreateTool(Tool):
    name = "reminder_create"
    description = (
        "Agenda um lembrete ou ação automática. schedule aceita horários amigáveis: "
        "'17:30', 'amanhã às 17:30', 'segunda às 09:00', 'todo dia 09:00', "
        "'a cada 30 minutos', 'a cada 2 horas', 'em 30 minutos', "
        "'2026-09-07 09:00' ou cron de 5 campos. "
        "action pode ser 'notify' (avisar o usuário) ou open_app/open_url/open_file/task_execute."
    )
    permission = ToolPermission.write

    def __init__(self, reminder_service: Any) -> None:
        self.reminder_service = reminder_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            view = await self.reminder_service.create_reminder(
                title=str(kwargs.get("title", "")),
                schedule_text=str(kwargs.get("schedule", "")),
                action=str(kwargs.get("action", "notify")),
                params=dict(kwargs.get("params") or {}),
            )
        except ValueError as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        return ToolResult(name=self.name, success=True, data={"reminder": view.to_dict()})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título/resumo do lembrete"},
                "schedule": {"type": "string", "description": "Horário humano ou cron"},
                "action": {"type": "string", "description": "Ação a executar (padrão: notify)"},
                "params": {
                    "type": "object",
                    "description": "Parâmetros da ação; para notify use {'message': '...'}",
                },
            },
            "required": ["title", "schedule"],
        }