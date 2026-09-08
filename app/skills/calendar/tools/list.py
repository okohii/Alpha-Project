from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


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


def _parse_iso(text: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)