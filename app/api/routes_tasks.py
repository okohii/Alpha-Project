from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.session import get_session
from app.skills.files.service import FileManager
from app.tasks.service import ManagedPathRepository, TaskExecutorService, TaskRepository

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    action: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)


class TaskRegisterPathRequest(BaseModel):
    path: str = Field(min_length=1)
    entry_type: str = Field(default="directory")
    source: str = Field(default="task_executor")


async def _executor_service(session) -> TaskExecutorService:
    path_repo = ManagedPathRepository(session)
    file_manager = FileManager()
    allowed_paths = await path_repo.list()
    resolved = [
        Path(record.path).expanduser().resolve()
        for record in allowed_paths
        if getattr(record, "is_allowed", 1)
    ]
    file_manager.allowed_directories = resolved
    return TaskExecutorService(TaskRepository(session), path_repo, file_manager)


@router.get("")
async def list_tasks(session=Depends(get_session)) -> list[dict]:
    service = _executor_service(session)
    tasks = await service.list_tasks(limit=50)
    return [task.__dict__ for task in tasks]


@router.post("")
async def create_task(payload: TaskCreateRequest, session=Depends(get_session)) -> dict:
    service = _executor_service(session)
    task = await service.create_task(
        title=payload.title,
        instruction=payload.instruction,
        action=payload.action,
        params=payload.params,
    )
    return {"task": task.__dict__}


@router.post("/{task_id}/execute")
async def execute_task(task_id: str, session=Depends(get_session)) -> dict:
    service = _executor_service(session)
    result = await service.execute_task(task_id)
    return {
        "success": result.success,
        "task_id": result.task_id,
        "result": result.result,
        "error": result.error,
    }


@router.post("/paths")
async def register_path(payload: TaskRegisterPathRequest, session=Depends(get_session)) -> dict:
    service = _executor_service(session)
    record = await service.register_allowed_path(
        payload.path,
        entry_type=payload.entry_type,
        source=payload.source,
    )
    return {
        "id": record.id,
        "path": record.path,
        "entry_type": record.entry_type,
        "is_allowed": bool(record.is_allowed),
    }
