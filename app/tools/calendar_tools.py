"""Ferramentas de agenda (calendário local)."""

from __future__ import annotations

from datetime import UTC, datetime
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


class CalendarListTool(Tool):
    name = "calendar_list"
    description = (
        "Lista eventos da agenda. Sem filtro, retorna os próximos (incluindo de hoje). "
        "Use 'from'/'to' com datas ISO (ex.: '2026-09-07 00:00') para um período."
    )
    permission = ToolPermission.read

    def __init__(self, calendar_service: Any) -> None:
        self.calendar_service = calendar_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        start = kwargs.get("from")
        end = kwargs.get("to")
        if start:
            start = _parse_iso(str(start))
        if end:
            end = _parse_iso(str(end))
        views = await self.calendar_service.list_events(
            start=start, end=end, limit=int(kwargs.get("limit", 100))
        )
        return ToolResult(
            name=self.name, success=True, data={"events": [v.to_dict() for v in views]}
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "from": {"type": "string", "description": "Início do período (ISO)"},
                "to": {"type": "string", "description": "Fim do período (ISO)"},
                "limit": {"type": "integer"},
            },
        }


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


def _parse_iso(text: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
