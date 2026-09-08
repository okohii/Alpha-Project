from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.tasks.service import TaskExecutorService
from app.tools.files import FileManager


class FakeTaskRepository:
    def __init__(self) -> None:
        self.items = []

    async def create(self, task):
        self.items.append(task)
        return task

    async def list(self, *args, **kwargs):
        return list(self.items)

    async def get(self, task_id):
        return next((item for item in self.items if item.id == task_id), None)

    async def save(self, task):
        for idx, item in enumerate(self.items):
            if item.id == task.id:
                self.items[idx] = task
                return task
        self.items.append(task)
        return task


class FakeManagedPathRepository:
    def __init__(self) -> None:
        self.items = []

    async def save(self, record):
        self.items.append(record)
        return record

    async def list(self):
        return list(self.items)


@pytest.mark.anyio
async def test_task_executor_registers_allowed_path_and_creates_task(tmp_path: Path):
    task_repo = FakeTaskRepository()
    path_repo = FakeManagedPathRepository()
    service = TaskExecutorService(task_repo, path_repo, FileManager([tmp_path]))

    saved_path = await service.register_allowed_path(
        str(tmp_path / "workspace"), entry_type="directory"
    )
    task = await service.create_task(
        title="Criar helper",
        instruction="Crie um método auxiliar para somar números.",
        action="create_method",
        params={
            "file_path": str(tmp_path / "helper.py"),
            "method_name": "sum_values",
            "method_body": "return sum(values)",
        },
    )

    assert saved_path.path.endswith("workspace")
    assert task.action == "create_method"
    assert task.status == "pending"


@pytest.mark.anyio
async def test_task_executor_creates_method_in_allowed_file(tmp_path: Path):
    file_path = tmp_path / "module.py"
    file_path.write_text("def existing():\n    return 1\n", encoding="utf-8")

    service = TaskExecutorService(
        FakeTaskRepository(), FakeManagedPathRepository(), FileManager([tmp_path])
    )
    task = await service.create_task(
        title="Adicionar utilitário",
        instruction="Adicione um método de soma.",
        action="create_method",
        params={
            "file_path": str(file_path),
            "method_name": "sum_values",
            "method_body": "return sum(values)",
        },
    )

    executed = await service.execute_task(task.id)

    assert executed.success is True
    assert "def sum_values" in file_path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_task_executor_persists_local_git_repo(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    remote_dir = tmp_path / "remote.git"
    repo_dir.mkdir()

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "config", "user.name", "alpha-test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "alpha@test.local"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("# alpha\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "remote", "add", "origin", str(remote_dir)], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    (repo_dir / "app.py").write_text("print('persisted')\n", encoding="utf-8")

    service = TaskExecutorService(
        FakeTaskRepository(), FakeManagedPathRepository(), FileManager([tmp_path])
    )
    task = await service.create_task(
        title="Persistir no Git",
        instruction="Salvar alteração no repositório e enviar para o origin.",
        action="persist_repo_changes",
        params={"repo_path": str(repo_dir), "message": "feat: persist local code"},
    )

    executed = await service.execute_task(task.id)

    assert executed.success is True
    assert (repo_dir / "app.py").exists()
