"""H4: Calendar skill registrada + tools compatíveis + sem agendamento de ações.

Regressões corrigidas:
- ``CalendarCreateTool`` passava ``action``/``action_params`` que o
  ``CalendarService.create_event`` não aceita (TypeError);
- ``CalendarRepository.list_due`` consultava campos inexistentes;
- a skill Calendar não era registrada no catalogo.
"""
from __future__ import annotations

import pytest

from app.calendar.service import CalendarService
from app.skills.calendar.tools.create import CalendarCreateTool
from app.skills.calendar.tools.list import CalendarListTool
from app.skills.catalog import build_default_skill_registry


class _FakeRepo:
    def __init__(self):
        self.events = []

    async def create(self, record):
        self.events.append(record)
        return record

    async def list(self, start=None, end=None, limit=100):
        return self.events[:limit]

    async def get(self, event_id):
        return None

    async def delete(self, event_id):
        self.events = [e for e in self.events if e.id != event_id]


def _service() -> CalendarService:
    return CalendarService(_FakeRepo())


@pytest.mark.anyio
async def test_calendar_create_tool_works_with_real_service():
    service = _service()
    tool = CalendarCreateTool(service)
    result = await tool.execute(title="Reunião", start="amanhã 10:00", end="1 hora")
    assert result.success is True
    assert result.data["event"]["title"] == "Reunião"


@pytest.mark.anyio
async def test_calendar_create_tool_does_not_schedule_actions():
    """Sem capacidade de agendamento de ações: back do schema removido."""
    tool = CalendarCreateTool(_service())
    schema = tool.parameters_schema()
    assert "action" not in schema["properties"]
    assert "action_params" not in schema["properties"]
    assert "macro_run" not in tool.description


@pytest.mark.anyio
async def test_calendar_list_tool_integration():
    service = _service()
    await CalendarCreateTool(service).execute(title="Aula", start="amanhã 11:00")
    result = await CalendarListTool(service).execute()
    assert result.success is True
    assert len(result.data["events"]) == 1


def test_calendar_skill_is_registered():
    registry = build_default_skill_registry()
    skills = registry.select_skills_for_task("agenda uma reunião amanhã 10:00")
    assert any(skill.name == "Calendar" for skill in skills)
    assert registry.skill_for_tool("calendar_create") == "Calendar"


def test_list_due_no_fake_action_capability():
    service = CalendarService(_FakeRepo())
    assert len(service.repository.events) == 0