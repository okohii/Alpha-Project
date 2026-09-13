from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.db.models import ReminderRecord

logger = logging.getLogger("app.reminders.service")

SAFE_ACTIONS: frozenset[str] = frozenset(
    {"open_app", "open_url", "open_file", "task_execute"}
)

_ONCE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_DELTA_RE = re.compile(
    r"^(?:em|daqui a|após|apos|daqui)\s+(\d+)\s*"
    r"(minuto|min|minutos|hora|horas|h|segundo|segundos|s)$",
    re.IGNORECASE,
)
_DAILY_RE = re.compile(
    r"^(?:todo dia|todos os dias|diariamente|todos dias)\s+(\d{1,2}):(\d{2})$",
    re.IGNORECASE,
)
_MONTHLY_RE = re.compile(
    r"^todo dia (\d{1,2})\s*(\d{1,2}):(\d{2})$",
    re.IGNORECASE,
)
_TOMORROW_RE = re.compile(
    r"^amanh[ãa]\s*(?:às|as| às| as)?\s*(\d{1,2}):(\d{2})$",
    re.IGNORECASE,
)
_WEEKDAY_RE = re.compile(
    r"^(?:todo\s+)?(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)\s*(?:às|as)?\s*(\d{1,2}):(\d{2})$",
    re.IGNORECASE,
)
_EVERY_RE = re.compile(
    r"^a cada\s+(?:(?P<amount>\d+)\s*)?"
    r"(?P<unit>minuto|min|minutos|hora|horas|h|dia|dias|semana|semanas)$",
    re.IGNORECASE,
)

_WEEKDAY_MAP = {
    "segunda": 0,
    "terça": 1,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sábado": 5,
    "sabado": 5,
    "domingo": 6,
}


@dataclass(slots=True)
class ReminderRecordView:
    id: str
    title: str
    schedule_type: str
    schedule: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    error: str | None = None

    @classmethod
    def from_model(cls, record: ReminderRecord) -> ReminderRecordView:
        return cls(
            id=record.id,
            title=record.title,
            schedule_type=record.schedule_type,
            schedule=record.schedule,
            action=record.action,
            params=dict(record.params or {}),
            enabled=bool(record.enabled),
            last_run_at=record.last_run_at,
            next_run_at=record.next_run_at,
            error=record.error,
        )

    def to_dict(self) -> dict[str, Any]:
        def _to_local(dt: datetime | None) -> str | None:
            if dt is None:
                return None
            # Converte UTC para horário local do usuário (UTC-3 Brasília)
            from datetime import timezone
            local_tz = timezone(timedelta(hours=-3))
            local_dt = dt.astimezone(local_tz)
            return local_dt.strftime("%Y-%m-%d %H:%M")
        
        return {
            "id": self.id,
            "title": self.title,
            "schedule_type": self.schedule_type,
            "schedule": self.schedule,
            "action": self.action,
            "params": self.params,
            "enabled": self.enabled,
            "last_run_at": _to_local(self.last_run_at),
            "next_run_at": _to_local(self.next_run_at),
            "error": self.error,
        }


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def parse_schedule(
    text: str, now: datetime | None = None
) -> tuple[str, str]:
    """Interpreta um horário humano e devolve (tipo, valor normalizado).

    Tipos: "once" (datetime ISO em UTC) e "cron" (expressão de 5 campos).
    Formatos aceitos:
      - "17:30" (próxima ocorrência hoje ou amanhã)
      - "2026-09-07 09:00"
      - "em 30 minutos" / "daqui a 2 horas"
      - "todo dia 09:00"
      - "amanhã às 17:30"
      - "segunda às 09:00" / "todo segunda às 09:00"
      - "a cada 30 minutos" / "a cada 2 horas"
      - cron de 5 campos, ex.: "0 9 * * 1-5"
    """
    from datetime import timezone
    
    raw = (text or "").strip().lower().replace("às ", "").replace("as ", "")
    
    # Fuso horário do usuário: UTC-3 (Brasília)
    local_tz = timezone(timedelta(hours=-3))
    
    # Usa horário fornecido ou horário atual do usuário
    if now is not None:
        # Converte para horário local se necessário
        if now.tzinfo is None:
            base = now.replace(tzinfo=UTC).astimezone(local_tz)
        else:
            base = now.astimezone(local_tz)
    else:
        base = datetime.now(local_tz)

    if not raw:
        raise ValueError("Horário vazio.")

    if _ONCE_RE.match(text.strip()):
        parsed = datetime.fromisoformat(text.strip().replace(" ", "T"))
        if parsed.tzinfo is None:
            # Interpreta como horário local do usuário
            parsed = parsed.replace(tzinfo=local_tz)
        parsed = parsed.astimezone(UTC)
        return "once", parsed.isoformat()

    # "amanhã às 17:30"
    tomorrow = _TOMORROW_RE.match(raw)
    if tomorrow:
        scheduled = (base + timedelta(days=1)).replace(
            hour=int(tomorrow.group(1)), minute=int(tomorrow.group(2)), second=0, microsecond=0
        )
        return "once", scheduled.astimezone(UTC).isoformat()

    # "segunda às 09:00" / "todo segunda às 09:00"
    weekday_match = _WEEKDAY_RE.match(raw)
    if weekday_match:
        day_name = weekday_match.group(1).lower()
        target_weekday = _WEEKDAY_MAP.get(day_name)
        if target_weekday is not None:
            hour = int(weekday_match.group(2))
            minute = int(weekday_match.group(3))
            days_ahead = (target_weekday - base.weekday()) % 7
            if days_ahead == 0:
                # Se é o mesmo dia, verifica se o horário já passou
                candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate <= base:
                    days_ahead = 7
            scheduled = (base + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return "once", scheduled.astimezone(UTC).isoformat()

    match = _TIME_RE.match(raw)
    if match and not _DAILY_RE.match(raw):
        scheduled = base.replace(
            hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0
        )
        if scheduled <= base:
            scheduled += timedelta(days=1)
        return "once", scheduled.astimezone(UTC).isoformat()

    daily = _DAILY_RE.match(raw)
    if daily:
        # Converte horário local para UTC
        hour = int(daily.group(1)) % 24
        minute = int(daily.group(2))
        # Ajusta para UTC-3: 08:00 local = 11:00 UTC
        utc_hour = (hour + 3) % 24
        minutes = f"{minute:02d}"
        hours = f"{utc_hour:02d}"
        return "cron", f"{minutes} {hours} * * *"

    # "todo dia 14 às 14:30" (dia do mês)
    monthly = _MONTHLY_RE.match(raw)
    if monthly:
        day = int(monthly.group(1))
        hour = int(monthly.group(2))
        minute = int(monthly.group(3))
        utc_hour = (hour + 3) % 24
        return "cron", f"{minute:02d} {utc_hour:02d} {day} * *"

    delta = _DELTA_RE.match(raw)
    if delta:
        amount = int(delta.group(1))
        unit = delta.group(2).lower()
        if unit.startswith("minuto") or unit == "min":
            seconds = amount * 60
        elif unit.startswith("hora") or unit == "h":
            seconds = amount * 3600
        else:
            seconds = amount
        return "once", (base + timedelta(seconds=seconds)).astimezone(UTC).isoformat()

    # "a cada 30 minutos" / "a cada 2 horas" / "a cada 3 dias" / "a cada hora"
    every_match = _EVERY_RE.match(raw)
    if every_match:
        amount = int(every_match.group("amount") or 1)
        unit = (every_match.group("unit") or "hora").lower()
        if unit.startswith("minuto") or unit == "min":
            return "cron", f"*/{amount} * * * *"
        elif unit.startswith("hora") or unit == "h":
            # "a cada hora" vira */* 1 2 3...
            return "cron", f"0 */{amount} * * *"
        elif unit.startswith("dia"):
            return "cron", f"0 0 */{amount} * *"
        elif unit.startswith("semana"):
            return "cron", f"0 0 * * */{amount}"

    try:
        from croniter import croniter
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("croniter não instalado; rode: pip install croniter") from exc
    if _has_valid_cron(croniter, raw, base):
        return "cron", raw

    raise ValueError(
        f'Não entendi o horário "{text}". Use: "17:30", "amanhã às 17:30", '
        '"segunda às 09:00", "todo dia 09:00", "a cada 30 minutos", '
        '"2026-09-07 09:00", "em 30 minutos" ou uma expressão cron de 5 campos.'
    )


def _has_valid_cron(croniter: Any, expression: str, base: datetime) -> bool:
    try:
        croniter(expression, base).get_next(datetime)
        return True
    except Exception:
        return False


def compute_next_run(
    schedule_type: str, schedule: str, after: datetime | None = None
) -> datetime | None:
    after = _as_utc(after or datetime.now(UTC)) or datetime.now(UTC)
    if schedule_type == "once":
        parsed = _as_utc(datetime.fromisoformat(schedule))
        if parsed is None:
            return None
        return parsed if parsed > after else None
    try:
        from croniter import croniter
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("croniter não instalado; rode: pip install croniter") from exc
    return croniter(schedule, after).get_next(datetime)


class ReminderRepository:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def create(self, record: ReminderRecord) -> ReminderRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def save(self, record: ReminderRecord) -> ReminderRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get(self, reminder_id: str) -> ReminderRecord | None:
        return await self.session.get(ReminderRecord, reminder_id)

    async def list(self, limit: int = 100) -> list[ReminderRecord]:
        from sqlalchemy import select

        result = await self.session.execute(
            select(ReminderRecord).order_by(ReminderRecord.next_run_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_due(self, now: datetime) -> list[ReminderRecord]:
        from sqlalchemy import select

        statement = (
            select(ReminderRecord)
            .where(ReminderRecord.enabled == 1)
            .where(ReminderRecord.next_run_at.isnot(None))
            .where(ReminderRecord.next_run_at <= now)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def delete(self, reminder_id: str) -> None:
        record = await self.get(reminder_id)
        if record is not None:
            await self.session.delete(record)
            await self.session.commit()


class ReminderService:
    def __init__(self, repository: ReminderRepository) -> None:
        self.repository = repository

    async def create_reminder(
        self,
        title: str,
        schedule_text: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> ReminderRecordView:
        action = (action or "").strip()
        if action != "notify" and action not in SAFE_ACTIONS:
            raise ValueError(
                f"Ação não permitida no agendador: {action}. Use: "
                f"notify, {', '.join(sorted(SAFE_ACTIONS))}."
            )
        schedule_type, schedule = parse_schedule(schedule_text)
        next_run = compute_next_run(schedule_type, schedule)
        if next_run is None:
            raise ValueError("O horário informado já passou.")
        record = ReminderRecord(
            id=str(uuid4()),
            title=title or schedule_text,
            schedule_type=schedule_type,
            schedule=schedule,
            action=action,
            params=params or {},
            enabled=1,
            next_run_at=next_run,
            last_run_at=None,
            error=None,
        )
        saved = await self.repository.create(record)
        return ReminderRecordView.from_model(saved)

    async def list_reminders(self, limit: int = 100) -> list[ReminderRecordView]:
        records = await self.repository.list(limit=limit)
        return [ReminderRecordView.from_model(record) for record in records]

    async def delete_reminder(self, reminder_id: str) -> None:
        await self.repository.delete(reminder_id)

    async def process_due(
        self, action_runner: Any, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Executa os lembretes vencidos e agenda a próxima ocorrência."""
        run_at = _as_utc(now or datetime.now(UTC)) or datetime.now(UTC)
        due = await self.repository.list_due(run_at)
        results: list[dict[str, Any]] = []
        for record in due:
            outcome: dict[str, Any] = {}
            try:
                outcome = await action_runner(record.action, dict(record.params or {}))
                record.error = None
            except Exception as exc:  # noqa: BLE001 - falha não derruba a fila
                record.error = str(exc)
                outcome = {"error": str(exc)}
            record.last_run_at = run_at
            next_run = compute_next_run(record.schedule_type, record.schedule, after=run_at)
            record.next_run_at = next_run
            if record.schedule_type == "once" and next_run is None:
                record.enabled = 0
            try:
                await self.repository.save(record)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Falha ao salvar lembrete %s: %s", record.id, exc)
            results.append(
                {
                    "reminder_id": record.id,
                    "title": record.title,
                    "action": record.action,
                    "success": record.error is None,
                    "result": outcome,
                    "error": record.error,
                    "next_run_at": next_run.isoformat() if next_run is not None else None,
                }
            )
        return results