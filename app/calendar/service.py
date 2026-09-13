from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core.scheduling import as_utc, now_utc
from app.db.models import CalendarEventRecord

logger = logging.getLogger("app.calendar.service")

DEFAULT_DURATION_MINUTES = 60
DEFAULT_START_HOUR = 9
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?$")
_BR_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?:[ T](\d{1,2}):(\d{2}))?$")
_DAYWORD_RE = re.compile(r"^(amanh(?:ã|a)|hoje)(?:[ \t]+(?:às|as))?[ \t]*((?:\d{1,2}):(?:\d{2}))?$")
_WEEKDAY_RE = re.compile(r"^(segunda|ter(?:ç|c)a|quarta|quinta|sexta|s(?:á|a)bado|domingo)(?:[- ]?feira)?(?:[ \t]+(?:às|as))?[ \t]*((?:\d{1,2}):(?:\d{2}))?$")
_DURATION_RE = re.compile(r"^(\d+)\s*(minuto|min|minutos|hora|horas|h|segundo|segundos|s)$", re.IGNORECASE)
_WEEKDAY_INDEX = {"segunda": 0, "terca": 1, "terça": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "sábado": 5, "domingo": 6}


@dataclass(slots=True)
class CalendarEventView:
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    description: str | None = None
    location: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, record: CalendarEventRecord) -> CalendarEventView:
        return cls(record.id, record.title, record.start_at, record.end_at, record.description, record.location, record.created_at)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "start_at": self.start_at.isoformat() if self.start_at else None, "end_at": self.end_at.isoformat() if self.end_at else None, "description": self.description, "location": self.location, "created_at": self.created_at.isoformat() if self.created_at else None}


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


def _resolve_time(base: datetime, hour: int, minute: int) -> datetime:
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _next_weekday(now: datetime, weekday_index: int) -> datetime:
    days_ahead = weekday_index - now.weekday()
    if days_ahead < 0 or (days_ahead == 0 and now.hour >= DEFAULT_START_HOUR):
        days_ahead += 7
    return now + timedelta(days=days_ahead)


def parse_start(text: str, now: datetime | None = None) -> datetime:
    base = as_utc(now or now_utc()) or now_utc()
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Horário de início vazio.")
    norm = _normalize(raw).lower()
    iso = _ISO_RE.match(norm.replace(" às ", " ").replace(" às", ""))
    if iso:
        year, month, day = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        hour, minute = int(iso.group(4)) if iso.group(4) else DEFAULT_START_HOUR, int(iso.group(5)) if iso.group(5) else 0
        return _resolve_time(base.replace(year=year, month=month, day=day), hour, minute)
    br = _BR_RE.match(norm.replace(" às ", " ").replace(" às", ""))
    if br:
        day, month = int(br.group(1)), int(br.group(2)); year = int(br.group(3)) if br.group(3) else base.year
        if year < 100: year += 2000
        try: return _resolve_time(base.replace(year=year, month=month, day=day), int(br.group(4)) if br.group(4) else DEFAULT_START_HOUR, int(br.group(5)) if br.group(5) else 0)
        except ValueError as exc: raise ValueError(f"Data inválida: {raw}") from exc
    dayword = _DAYWORD_RE.match(norm)
    if dayword:
        offset = 1 if dayword.group(1).startswith("amanh") else 0
        hour, minute = (map(int, dayword.group(2).split(":")) if dayword.group(2) else (DEFAULT_START_HOUR, 0))
        return _next_weekday_hour(base, offset, hour, minute)
    weekday = _WEEKDAY_RE.match(norm)
    if weekday:
        index = _WEEKDAY_INDEX.get(weekday.group(1), 0); hour, minute = (map(int, weekday.group(2).split(":")) if weekday.group(2) else (DEFAULT_START_HOUR, 0))
        target = base + timedelta(days=(index - base.weekday()) % 7); scheduled = _resolve_time(target, hour, minute)
        return _resolve_time(target + timedelta(days=7), hour, minute) if scheduled <= base else scheduled
    match = _TIME_RE.match(norm)
    if match:
        scheduled = _resolve_time(base, int(match.group(1)) % 24, int(match.group(2)))
        return scheduled + timedelta(days=1) if scheduled <= base else scheduled
    if _DURATION_RE.match(norm):
        raise ValueError(f'"{text}" é uma duração; para o início use um horário como "15:00", "amanhã 10:00" ou "2026-09-07 09:00".')
    raise ValueError(f'Não entendi o horário "{text}". Use: "17:30", "amanhã 10:00", "segunda 09:00", "2026-09-07 09:00" ou "17/12 14:30".')


def _next_weekday_hour(base: datetime, day_offset: int, hour: int, minute: int) -> datetime:
    target = (base + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0); scheduled = _resolve_time(target, hour, minute)
    return scheduled + timedelta(days=1) if scheduled <= base else scheduled


def parse_duration(text: str | None) -> timedelta | None:
    if not text: return None
    match = _DURATION_RE.match((text or "").strip().lower().replace("daqui a ", "").replace("em ", ""))
    if not match: return None
    amount, unit = int(match.group(1)), match.group(2)
    if unit.startswith("minuto") or unit == "min": return timedelta(minutes=amount)
    if unit.startswith("hora") or unit == "h": return timedelta(hours=amount)
    return timedelta(seconds=amount)


def parse_end(text: str | None, start: datetime, now: datetime | None = None) -> datetime:
    if not (text or "").strip(): return start + timedelta(minutes=DEFAULT_DURATION_MINUTES)
    duration = parse_duration(text)
    if duration is not None: return start + duration
    match = _TIME_RE.match((text or "").strip().lower())
    if match:
        end = _resolve_time(start, int(match.group(1)) % 24, int(match.group(2)))
        if end <= start: raise ValueError("O fim deve ser depois do início do evento.")
        return end
    end = parse_start(text, now=start)
    if end <= start: raise ValueError("O fim deve ser depois do início do evento.")
    return end


class CalendarRepository:
    def __init__(self, session: Any) -> None: self.session = session
    async def create(self, record): self.session.add(record); await self.session.commit(); await self.session.refresh(record); return record
    async def get(self, event_id): return await self.session.get(CalendarEventRecord, event_id)
    async def list(self, start=None, end=None, limit=100):
        from sqlalchemy import select
        statement = select(CalendarEventRecord).order_by(CalendarEventRecord.start_at)
        if start is not None: statement = statement.where(CalendarEventRecord.end_at >= start)
        if end is not None: statement = statement.where(CalendarEventRecord.start_at <= end)
        result = await self.session.execute(statement.limit(limit)); return list(result.scalars().all())
    async def list_due(self, now): return []
    async def delete(self, event_id):
        record = await self.get(event_id)
        if record is not None: await self.session.delete(record); await self.session.commit()


class CalendarService:
    def __init__(self, repository): self.repository = repository
    async def create_event(self, title, start_text, end_text=None, description=None, location=None, now=None):
        title = (title or "").strip()
        if not title: raise ValueError("Informe o título do evento.")
        base = as_utc(now or now_utc()) or now_utc(); start = parse_start(start_text, base)
        if start <= base: raise ValueError("O início do evento já passou.")
        end = parse_end(end_text, start, base)
        record = CalendarEventRecord(id=str(uuid4()), title=title, description=description or None, location=location or None, start_at=start, end_at=end)
        return CalendarEventView.from_model(await self.repository.create(record))
    async def list_events(self, start=None, end=None, limit=100): return [CalendarEventView.from_model(r) for r in await self.repository.list(start=as_utc(start), end=as_utc(end), limit=limit)]
    async def upcoming(self, limit=10, now=None): return await self.list_events(start=as_utc(now or now_utc()), limit=limit)
    async def delete_event(self, event_id): await self.repository.delete(event_id)
