from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.calendar.service import (
    CalendarService,
    parse_duration,
    parse_end,
    parse_start,
)
from app.database.models import CalendarEventRecord


def _now() -> datetime:
    return datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


def test_parse_start_time_later_today():
    result = parse_start("17:30", now=_now())
    assert result == datetime(2026, 9, 6, 17, 30, tzinfo=UTC)


def test_parse_start_time_past_rolls_to_tomorrow():
    result = parse_start("10:00", now=_now())
    assert result == datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def test_parse_start_amanha_with_time():
    result = parse_start("amanhã 10:00", now=_now())
    assert result == datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def test_parse_start_amanha_default_hour():
    result = parse_start("amanhã", now=_now())
    assert result == datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def test_parse_start_today():
    result = parse_start("hoje 15:00", now=_now())
    assert result == datetime(2026, 9, 6, 15, 0, tzinfo=UTC)


def test_parse_start_weekday_next_occurrence():
    # 2026-09-06 é domingo; "segunda 09:00" deve cair em 2026-09-07.
    result = parse_start("segunda 09:00", now=_now())
    assert result == datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def test_parse_start_iso_datetime():
    result = parse_start("2026-09-07 09:00", now=_now())
    assert result == datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def test_parse_start_iso_date_default_9h():
    result = parse_start("2026-09-07", now=_now())
    assert result == datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def test_parse_start_br_date():
    result = parse_start("17/12 14:30", now=_now())
    assert result == datetime(2026, 12, 17, 14, 30, tzinfo=UTC)


def test_parse_start_relative_not_allowed_at_start():
    with pytest.raises(ValueError):
        parse_start("em 2 horas", now=_now())


def test_parse_start_rejects_garbage():
    with pytest.raises(ValueError):
        parse_start("algum dia desses", now=_now())


def test_parse_start_rejects_empty():
    with pytest.raises(ValueError):
        parse_start("", now=_now())


def test_parse_duration_minutes():
    assert parse_duration("30 minutos") == timedelta(minutes=30)


def test_parse_duration_hours():
    assert parse_duration("1 hora") == timedelta(hours=1)


def test_parse_duration_none():
    assert parse_duration(None) is None
    assert parse_duration("xablau") is None


def test_parse_end_absolute_after_start():
    start = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    assert parse_end("18:00", start, now=_now()) == datetime(2026, 9, 7, 18, 0, tzinfo=UTC)


def test_parse_end_defaults_to_one_hour():
    start = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    assert parse_end(None, start, now=_now()) == start + timedelta(hours=1)


def test_parse_end_duration_relative():
    start = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    assert parse_end("30 minutos", start, now=_now()) == start + timedelta(minutes=30)


def test_parse_end_before_start_raises():
    start = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        parse_end("09:00", start, now=_now())


class FakeCalendarRepository:
    def __init__(self) -> None:
        self.items: list[CalendarEventRecord] = []

    async def create(self, record):
        self.items.append(record)
        return record

    async def get(self, event_id: str):
        return next((item for item in self.items if item.id == event_id), None)

    async def list(self, start=None, end=None, limit=100):
        ordered = sorted(self.items, key=lambda item: item.start_at)
        if start is not None:
            ordered = [item for item in ordered if item.end_at >= start]
        if end is not None:
            ordered = [item for item in ordered if item.start_at <= end]
        return ordered[-limit:]

    async def delete(self, event_id: str):
        self.items = [item for item in self.items if item.id != event_id]


@pytest.mark.anyio
async def test_create_event_success():
    repo = FakeCalendarRepository()
    service = CalendarService(repo)
    view = await service.create_event("Reunião", "amanhã 10:00", end_text="1 hora", now=_now())
    assert view.title == "Reunião"
    assert view.start_at.hour == 10
    assert (view.end_at - view.start_at) == timedelta(hours=1)


@pytest.mark.anyio
async def test_create_event_default_duration():
    repo = FakeCalendarRepository()
    service = CalendarService(repo)
    view = await service.create_event("Almoço", "amanhã 12:00", now=_now())
    assert (view.end_at - view.start_at) == timedelta(hours=1)


@pytest.mark.anyio
async def test_create_event_rejects_past_start():
    repo = FakeCalendarRepository()
    service = CalendarService(repo)
    with pytest.raises(ValueError):
        await service.create_event("Passado", "2026-09-05 09:00", now=_now())


@pytest.mark.anyio
async def test_create_event_rejects_empty_title():
    repo = FakeCalendarRepository()
    service = CalendarService(repo)
    with pytest.raises(ValueError):
        await service.create_event("", "amanhã 10:00", now=_now())


@pytest.mark.anyio
async def test_upcoming_filters_past_and_orders():
    repo = FakeCalendarRepository()
    future = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    past = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    repo.items = [
        _make_event("futuro", future, future + timedelta(hours=1)),
        _make_event("passado", past, past + timedelta(hours=1)),
    ]
    service = CalendarService(repo)
    views = await service.upcoming(limit=10, now=_now())
    assert [v.title for v in views] == ["futuro"]


@pytest.mark.anyio
async def test_delete_event():
    repo = FakeCalendarRepository()
    event = _make_event("evento", _now() + timedelta(days=1), _now() + timedelta(days=1, hours=1))
    repo.items.append(event)
    service = CalendarService(repo)
    await service.delete_event(event.id)
    assert repo.items == []


def _make_event(title, start_at: datetime, end_at: datetime) -> CalendarEventRecord:
    return CalendarEventRecord(
        id=str(uuid4()),
        title=title,
        start_at=start_at,
        end_at=end_at,
        description=None,
        location=None,
    )
