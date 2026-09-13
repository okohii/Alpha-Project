from __future__ import annotations

import asyncio
import subprocess
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.models import ManagedPathRecord, TaskRecord
from app.skills.files.service import FileManager


@dataclass(slots=True)
class TaskExecutionResult:
    success: bool
    task_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class TaskRecordView:
    id: str
    title: str
    instruction: str
    action: str
    status: str
    params: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_model(cls, task: TaskRecord) -> TaskRecordView:
        return cls(
            id=task.id,
            title=task.title,
            instruction=task.instruction,
            action=task.action,
            status=task.status,
            params=dict(task.params or {}),
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class TaskRepository:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def create(self, task: TaskRecord) -> TaskRecord:
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def list(self, limit: int = 50) -> list[TaskRecord]:
        from sqlalchemy import select

        result = await self.session.execute(
            select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get(self, task_id: str) -> TaskRecord | None:
        return await self.session.get(TaskRecord, task_id)

    async def save(self, task: TaskRecord) -> TaskRecord:
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task


class ManagedPathRepository:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def save(self, record: ManagedPathRecord) -> ManagedPathRecord:
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def list(self) -> list[ManagedPathRecord]:
        from sqlalchemy import select

        result = await self.session.execute(
            select(ManagedPathRecord).order_by(ManagedPathRecord.created_at.desc())
        )
        return list(result.scalars().all())


class TaskExecutorService:
    def __init__(
        self,
        task_repository: Any,
        managed_path_repository: Any,
        file_manager: FileManager,
    ) -> None:
        self.task_repository = task_repository
        self.managed_path_repository = managed_path_repository
        self.file_manager = file_manager

    async def register_allowed_path(
        self,
        path: str,
        entry_type: str = "directory",
        source: str = "task_executor",
    ) -> ManagedPathRecord:
        normalized = Path(path).expanduser().resolve()
        if self.file_manager is not None:
            self.file_manager._ensure_allowed(normalized)
            if normalized not in self.file_manager.allowed_directories:
                self.file_manager.allowed_directories.append(normalized)
        record = ManagedPathRecord(
            path=str(normalized),
            entry_type=entry_type,
            is_allowed=1,
            source=source,
            metadata_={"registered_at": datetime.now(UTC).isoformat()},
            last_seen_at=datetime.now(UTC),
        )
        if self.managed_path_repository is not None:
            return await self.managed_path_repository.save(record)
        return record

    async def sync_allowed_paths(self) -> list[Path]:
        if self.managed_path_repository is None:
            return list(self.file_manager.allowed_directories)

        records = await self.managed_path_repository.list()
        paths = [
            Path(record.path).expanduser().resolve()
            for record in records
            if getattr(record, "is_allowed", 1) and getattr(record, "path", None)
        ]
        unique_paths: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path)
            if key not in seen:
                unique_paths.append(path)
                seen.add(key)
        self.file_manager.allowed_directories = unique_paths
        return unique_paths

    async def list_allowed_paths(self) -> list[dict[str, Any]]:
        if self.managed_path_repository is None:
            return []
        records = await self.managed_path_repository.list()
        return [
            {
                "id": record.id,
                "path": record.path,
                "entry_type": record.entry_type,
                "is_allowed": bool(record.is_allowed),
            }
            for record in records
        ]

    async def create_task(
        self,
        title: str,
        instruction: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> TaskRecordView:
        task = TaskRecord(
            id=str(uuid4()),
            title=title,
            instruction=instruction,
            action=action,
            status="pending",
            params=params or {},
            result=None,
            error=None,
            started_at=None,
            finished_at=None,
        )
        saved = await self.task_repository.create(task)
        return TaskRecordView.from_model(saved)

    async def get_task(self, task_id: str) -> TaskRecordView | None:
        task = await self.task_repository.get(task_id)
        return TaskRecordView.from_model(task) if task else None

    async def list_tasks(self, limit: int = 50) -> list[TaskRecordView]:
        tasks = await self.task_repository.list(limit=limit)
        return [TaskRecordView.from_model(task) for task in tasks]

    async def execute_task(self, task_id: str) -> TaskExecutionResult:
        task = await self.task_repository.get(task_id)
        if task is None:
            return TaskExecutionResult(success=False, error="Task not found")

        task.status = "running"
        task.started_at = datetime.now(UTC)
        await self.task_repository.save(task)

        try:
            result = await self._run_action(task.action, task.params)
            task.status = "completed"
            task.result = result
            task.error = None
            task.finished_at = datetime.now(UTC)
            await self.task_repository.save(task)
            return TaskExecutionResult(success=True, task_id=task.id, result=result)
        except Exception as exc:  # pragma: no cover - defensive path
            task.status = "failed"
            task.error = str(exc)
            task.finished_at = datetime.now(UTC)
            await self.task_repository.save(task)
            return TaskExecutionResult(success=False, task_id=task.id, error=str(exc))

    async def _run_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "create_file":
            return self.file_manager.create_file(
                str(params["path"]), str(params.get("content", ""))
            )
        if action == "create_directory":
            return self.file_manager.create_directory(str(params["path"]))
        if action == "create_method":
            return self._create_method_in_file(**params)
        if action == "persist_repo_changes":
            return await asyncio.to_thread(self._persist_repo_changes, **params)
        if action == "open_browser":
            browser = params.get("browser", "default")
            url = str(params.get("url") or params.get("query") or "https://www.google.com")
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://www.google.com/search?q=" + url.replace(" ", "+")
            webbrowser.get(browser).open(url) if browser != "default" else webbrowser.open(url)
            return {"opened": True, "url": url, "browser": browser}
        if action == "search_web":
            query = str(params.get("query", ""))
            target = "https://www.google.com/search?q=" + query.replace(" ", "+")
            webbrowser.open(target)
            return {"searched": True, "query": query, "url": target}
        if action == "list_directory":
            return {"items": self.file_manager.list_directory(str(params["path"]))}
        raise ValueError(f"Ação não suportada: {action}")

    def _create_method_in_file(
        self,
        file_path: str,
        method_name: str,
        method_body: str,
        class_name: str | None = None,
    ) -> dict[str, Any]:
        file = Path(file_path).expanduser().resolve()
        self.file_manager._ensure_allowed(file)

        if not file.exists():
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("", encoding="utf-8")

        content = file.read_text(encoding="utf-8", errors="ignore")
        if not content.strip():
            content = "\n"

        if f"def {method_name}" in content:
            raise ValueError(f"Método '{method_name}' já existe no arquivo.")

        body = method_body.strip()
        if class_name:
            indent = "        "
            block = (
                f"\n    def {method_name}(self, *args, **kwargs):\n"
                f"        {body.replace(chr(10), chr(10) + indent)}\n"
            )
            if "class " not in content:
                content = f"class {class_name}:\n{block}\n" + content
            else:
                content = content.rstrip() + "\n" + block + "\n"
        else:
            indent = "    "
            block = (
                f"\ndef {method_name}(*args, **kwargs):\n"
                f"    {body.replace(chr(10), chr(10) + indent)}\n"
            )
            content = content.rstrip() + block + "\n"

        file.write_text(content, encoding="utf-8")
        return {"path": str(file), "method": method_name, "created": True}

    def _persist_repo_changes(
        self,
        repo_path: str,
        message: str | None = None,
        branch: str | None = None,
        remote: str | None = None,
    ) -> dict[str, Any]:
        repo = Path(repo_path).expanduser().resolve()
        if not repo.exists() or not (repo / ".git").exists():
            raise ValueError(f"Repositório inválido ou inexistente: {repo}")

        current_branch = branch or self._git(repo, "branch", "--show-current").strip() or "main"
        try:
            self._git(repo, "pull", "--rebase", "origin", current_branch)
        except subprocess.CalledProcessError:
            self._git(repo, "pull", "--rebase", "origin", current_branch, allow_fail=True)

        self._git(repo, "add", ".")
        status = self._git(repo, "status", "--short")
        if not status.strip():
            return {
                "repo": str(repo),
                "branch": current_branch,
                "message": message or "No changes to commit",
                "committed": False,
                "pushed": False,
            }

        commit_message = message or "chore: save agent changes"
        self._git(repo, "commit", "-m", commit_message)
        self._git(repo, "push", "origin", current_branch)

        return {
            "repo": str(repo),
            "branch": current_branch,
            "message": commit_message,
            "committed": True,
            "pushed": True,
        }

    def _git(self, repo: Path, *args: str, allow_fail: bool = False) -> str:
        completed = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
        if completed.returncode != 0 and not allow_fail:
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed.stdout + completed.stderr
