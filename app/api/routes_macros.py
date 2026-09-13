from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.macros.service import macro_service
from app.security.api_gate import EXECUTE_ACTION, require_local_api_auth

router = APIRouter(prefix="/macros", tags=["macros"])

_EXEC = Depends(require_local_api_auth(EXECUTE_ACTION))


# ── Pydantic models ────────────────────────────────────────────────────


class MacroStepIn(BaseModel):
    step_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    wait_after: float = 0.0
    description: str | None = None


class MacroCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    steps: list[MacroStepIn] = Field(..., min_length=1)
    parameters: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class MacroUpdate(BaseModel):
    description: str | None = None
    steps: list[MacroStepIn] | None = None
    parameters: list[str] | None = None
    tags: list[str] | None = None
    enabled: bool | None = None


class MacroOut(BaseModel):
    id: str
    name: str
    description: str | None
    parameters: list[str]
    tags: list[str]
    enabled: bool
    steps: list[dict[str, Any]]
    created_at: str | None
    updated_at: str | None


class ScheduleCreate(BaseModel):
    macro_id: str
    cron_expression: str | None = None
    run_at: datetime | None = None
    fixed_parameters: dict[str, Any] = Field(default_factory=dict)


class ScheduleOut(BaseModel):
    id: str
    macro_id: str
    cron_expression: str | None
    run_at: str | None
    fixed_parameters: dict[str, Any]
    enabled: bool
    last_run_at: str | None
    next_run_at: str | None
    run_count: int


class ExecuteRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)


# ── Macros CRUD ────────────────────────────────────────────────────────


@router.get("", response_model=list[MacroOut])
async def list_macros(enabled_only: bool = True):
    macros = await macro_service.list_macros(enabled_only=enabled_only)
    return [_macro_out(m) for m in macros]


@router.post("", response_model=MacroOut)
async def create_macro(data: MacroCreate, _auth=_EXEC):
    steps = [s.model_dump() for s in data.steps]
    macro = await macro_service.create_macro(
        name=data.name,
        description=data.description,
        steps=steps,
        parameters=data.parameters,
        tags=data.tags,
    )
    return _macro_out(macro)


@router.get("/{macro_id}", response_model=MacroOut)
async def get_macro(macro_id: str):
    macro = await macro_service.get_macro(macro_id)
    if not macro:
        raise HTTPException(404, "Macro não encontrada")
    return _macro_out(macro)


@router.put("/{macro_id}", response_model=MacroOut)
async def update_macro(macro_id: str, data: MacroUpdate, _auth=_EXEC):
    update_data = data.model_dump(exclude_unset=True)
    if "steps" in update_data:
        update_data["steps"] = [s.model_dump() for s in update_data["steps"]]
    macro = await macro_service.update_macro(macro_id, **update_data)
    if not macro:
        raise HTTPException(404, "Macro não encontrada")
    return _macro_out(macro)


@router.delete("/{macro_id}")
async def delete_macro(macro_id: str, _auth=_EXEC):
    ok = await macro_service.delete_macro(macro_id)
    if not ok:
        raise HTTPException(404, "Macro não encontrada")
    return {"ok": True}


@router.post("/{macro_id}/execute")
async def execute_macro(macro_id: str, request: ExecuteRequest, _auth=_EXEC):
    try:
        log = await macro_service.execute_macro(macro_id, request.parameters)
        return log.to_dict()
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ── Schedules (ANTES de /{macro_id} para evitar shadowing) ─────────────


@router.get("/schedules/list", response_model=list[ScheduleOut])
async def list_schedules(enabled_only: bool = True):
    schedules = await macro_service.list_scheduled(enabled_only=enabled_only)
    return [_schedule_out(s) for s in schedules]


@router.post("/schedules", response_model=ScheduleOut)
async def create_schedule(data: ScheduleCreate, _auth=_EXEC):
    try:
        scheduled = await macro_service.schedule_macro(
            macro_id=data.macro_id,
            cron_expression=data.cron_expression,
            run_at=data.run_at,
            fixed_parameters=data.fixed_parameters,
        )
        return _schedule_out(scheduled)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/schedules/{schedule_id}")
async def cancel_schedule(schedule_id: str, _auth=_EXEC):
    ok = await macro_service.cancel_scheduled(schedule_id)
    if not ok:
        raise HTTPException(404, "Agendamento não encontrado")
    return {"ok": True}


# ── Execution logs ─────────────────────────────────────────────────────


@router.get("/logs/list")
async def get_logs(macro_id: str | None = None, limit: int = 50):
    logs = await macro_service.get_execution_logs(macro_id=macro_id, limit=limit)
    return [log.to_dict() for log in logs]


# ── Helpers ────────────────────────────────────────────────────────────


def _macro_out(macro: Any) -> dict[str, Any]:
    return {
        "id": macro.id,
        "name": macro.name,
        "description": macro.description,
        "parameters": macro.parameters,
        "tags": macro.tags,
        "enabled": bool(macro.enabled),
        "steps": [s.to_dict() for s in macro.steps],
        "created_at": macro.created_at.isoformat() if macro.created_at else None,
        "updated_at": macro.updated_at.isoformat() if macro.updated_at else None,
    }


def _schedule_out(schedule: Any) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "macro_id": schedule.macro_id,
        "cron_expression": schedule.cron_expression,
        "run_at": schedule.run_at.isoformat() if schedule.run_at else None,
        "fixed_parameters": schedule.fixed_parameters,
        "enabled": bool(schedule.enabled),
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "run_count": schedule.run_count,
    }
