from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class CalendarCreateTool(Tool):
    name = "calendar_create"
    description = (
        "Cria um evento na agenda. start aceita '17:30', 'amanhã 10:00', 'segunda 09:00', "
        "'2026-09-07 09:00', '17/12 14:30' ou 'em 2 horas'. end (opcional) aceita "
        "'1 hora', '30 minutos' ou outro horário; sem end vale 1 hora."
    )
    permission = ToolPermission.write

    def __init__(self, calendar_service: Any) -> None:
        self.calendar_service = calendar_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            view = await self.calendar_service.create_event(
                title=str(kwargs.get("title", "")),
                start_text=str(kwargs.get("start", "")),
                end_text=str(kwargs.get("end")) if kwargs.get("end") else None,
                description=str(kwargs.get("description")) if kwargs.get("description") else None,
                location=str(kwargs.get("location")) if kwargs.get("location") else None,
            )
        except ValueError as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))
        return ToolResult(name=self.name, success=True, data={"event": view.to_dict()})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título do evento"},
                "start": {"type": "string", "description": "Início em linguagem natural"},
                "end": {"type": "string", "description": "Duração ou fim (padrão: 1 hora)"},
                "description": {"type": "string", "description": "Anotações do evento"},
                "location": {"type": "string", "description": "Local (ex.: 'escritório')"},
            },
            "required": ["title", "start"],
        }