from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.db.models import ReminderRecord
from app.reminders.service import (
    ReminderService,
    compute_next_run,
    parse_schedule,
)


def _now() -> datetime:
    return datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


def test_parse_schedule_once_later_today():
    kind, value = parse_schedule("15:30", now=_now())
    assert kind == "once"
    assert datetime.fromisoformat(value) > _now()


def test_parse_schedule_once_past_rolls_to_tomorrow():
    kind, value = parse_schedule("10:00", now=_now())
    assert kind == "once"
    parsed = datetime.fromisoformat(value)
    assert parsed.day == _now().day + 1


def test_parse_schedule_daily_becomes_cron():
    kind, value = parse_schedule("todo dia 09:00")
    assert kind == "cron"
    assert value == "00 09 * * *"


def test_parse_schedule_cron_passthrough():
    kind, value = parse_schedule("0 9 * * 1-5")
    assert kind == "cron"
    assert value == "0 9 * * 1-5"


def test_parse_schedule_relative_minutes():
    kind, value = parse_schedule("em 30 minutos", now=_now())
    assert kind == "once"
    assert datetime.fromisoformat(value) == _now() + timedelta(minutes=30)


def test_parse_schedule_relative_hours():
    kind, value = parse_schedule("daqui a 2 horas", now=_now())
    assert kind == "once"
    assert datetime.fromisoformat(value) == _now() + timedelta(hours=2)


def test_parse_schedule_explicit_datetime():
    kind, value = parse_schedule("2026-09-07 09:00")
    assert kind == "once"
    assert datetime.fromisoformat(value) == datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def test_parse_schedule_rejects_garbage():
    with pytest.raises(ValueError):
        parse_schedule("algum dia desses")


def test_compute_next_run_once_in_future():
    future = (_now() + timedelta(hours=3)).isoformat()
    assert compute_next_run("once", future, after=_now()) is not None


def test_compute_next_run_once_in_past_is_none():
    past = (_now() - timedelta(hours=3)).isoformat()
    assert compute_next_run("once", past, after=_now()) is None


def test_compute_next_run_cron_advances():
    next_run = compute_next_run("cron", "0 9 * * *", after=_now())
    assert next_run is not None
    assert next_run > _now()
    assert next_run.hour == 9


class FakeReminderRepository:
    def __init__(self) -> None:
        self.items: list[ReminderRecord] = []

    async def create(self, record):
        self.items.append(record)
        return record

    async def save(self, record):
        return record

    async def get(self, reminder_id: str):
        return next((item for item in self.items if item.id == reminder_id), None)

    async def list(self, limit: int = 100):
        return list(reversed(self.items[-limit:]))

    async def list_due(self, now):
        return [
            item
            for item in self.items
            if item.enabled and item.next_run_at is not None and item.next_run_at <= now
        ]

    async def delete(self, reminder_id: str):
        self.items = [item for item in self.items if item.id != reminder_id]


def _make_reminder(**overrides):
    defaults = dict(
        id=str(uuid4()),
        title="teste",
        schedule_type="once",
        schedule="2026-09-06T11:00:00+00:00",
        action="notify",
        params={},
        enabled=1,
        last_run_at=None,
        next_run_at=datetime(2026, 9, 6, 11, 0, tzinfo=UTC),
        error=None,
    )
    defaults.update(overrides)
    return ReminderRecord(**defaults)


@pytest.mark.anyio
async def test_create_reminder_rejects_unsafe_action():
    service = ReminderService(FakeReminderRepository())
    with pytest.raises(ValueError):
        await service.create_reminder("titulo", "18:00", "type_text", {"text": "oi"})


@pytest.mark.anyio
async def test_create_reminder_rejects_past_datetime():
    service = ReminderService(FakeReminderRepository())
    with pytest.raises(ValueError):
        await service.create_reminder("titulo", "2020-01-01 09:00", "notify")


@pytest.mark.anyio
async def test_create_reminder_accepts_safe_action():
    repo = FakeReminderRepository()
    service = ReminderService(repo)
    view = await service.create_reminder(
        "abrir discord", "todo dia 09:00", "open_app", {"app": "discord"}
    )

    assert view.action == "open_app"
    assert view.schedule_type == "cron"
    assert view.enabled is True
    assert view.next_run_at is not None


@pytest.mark.anyio
async def test_process_due_executes_once_and_disables():
    repo = FakeReminderRepository()
    reminder = _make_reminder()
    repo.items.append(reminder)
    service = ReminderService(repo)
    calls = []

    async def runner(action, params):
        calls.append((action, params))
        return {"notified": True}

    results = await service.process_due(runner, now=_now())

    assert calls == [("notify", {})]
    assert len(results) == 1
    assert results[0]["success"] is True
    assert reminder.enabled == 0
    assert reminder.last_run_at == _now()
    assert reminder.next_run_at is None


@pytest.mark.anyio
async def test_process_due_cron_keeps_running_and_advances():
    repo = FakeReminderRepository()
    reminder = _make_reminder(schedule_type="cron", schedule="0 9 * * *")
    repo.items.append(reminder)
    service = ReminderService(repo)

    async def runner(action, params):
        return {"ok": True}

    results = await service.process_due(runner, now=_now())

    assert len(results) == 1
    assert results[0]["success"] is True
    assert reminder.enabled == 1
    assert reminder.next_run_at is not None
    assert reminder.next_run_at > _now()


@pytest.mark.anyio
async def test_process_due_captures_errors():
    repo = FakeReminderRepository()
    reminder = _make_reminder(schedule_type="cron", schedule="0 9 * * *")
    repo.items.append(reminder)
    service = ReminderService(repo)

    async def runner(action, params):
        raise RuntimeError("app não está mais instalado")

    results = await service.process_due(runner, now=_now())

    assert results[0]["success"] is False
    assert "não está mais instalado" in results[0]["error"]
    assert reminder.error is not None


@pytest.mark.anyio
async def test_runner_start_stop_lifecycle():
    from app.reminders.runner import SchedulerRunner

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    runner = SchedulerRunner(lambda: FakeSession())
    await runner.start()
    assert runner._running
    await runner.stop()
    assert not runner._running
    assert runner._task is None


@pytest.mark.anyio
async def test_reminder_create_tool_success():
    from app.tools.reminders import ReminderCreateTool

    service = ReminderService(FakeReminderRepository())
    tool = ReminderCreateTool(service)
    result = await tool.execute(
        title="reunião", schedule="em 5 minutos", action="notify", params={"message": "reunião"}
    )
    assert result.success is True
    assert result.data["reminder"]["action"] == "notify"


@pytest.mark.anyio
async def test_reminder_create_tool_rejects_bad_schedule():
    from app.tools.reminders import ReminderCreateTool

    service = ReminderService(FakeReminderRepository())
    tool = ReminderCreateTool(service)
    result = await tool.execute(title="x", schedule="algum dia", action="notify")

    assert result.success is False
    assert result.error is not None


@pytest.mark.anyio
async def test_reminder_list_and_delete_tools():
    from app.tools.reminders import ReminderDeleteTool, ReminderListTool

    repo = FakeReminderRepository()
    repo.items.append(_make_reminder())
    service = ReminderService(repo)

    listed = await ReminderListTool(service).execute()
    assert listed.success is True
    assert len(listed.data["reminders"]) == 1

    reminder_id = repo.items[0].id
    deleted = await ReminderDeleteTool(service).execute(reminder_id=reminder_id)
    assert deleted.success is True
    assert repo.items == []