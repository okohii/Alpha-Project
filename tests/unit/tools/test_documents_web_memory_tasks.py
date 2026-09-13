"""Cobertura de tools antes sem teste direto (Fase 7.3): documentos, web,
memória (delete/procedures), tasks (create/execute/list) e câmera."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.skills.documents.tools.search import DocumentSearchTool
from app.skills.memory.tools.delete import MemoryDeleteTool
from app.skills.memory.tools.procedures import ProcedureRunTool, ProcedureSaveTool
from app.skills.memory.tools.save import MemorySaveTool
from app.skills.memory.tools.search import MemorySearchTool
from app.skills.tasks.tools.create import TaskCreateTool
from app.skills.tasks.tools.execute import TaskExecuteTool
from app.skills.tasks.tools.list import TaskListTool
from app.skills.tasks.tools.register_path import TaskRegisterPathTool
from app.skills.web.tools.search import WebSearchTool

# ---- documentos ----

class _FakeIndexer:
    async def search_documents(self, query: str, limit: int = 5):
        return {"query": query, "results": [{"chunk": "trecho", "path": "/a.txt"}]}


@pytest.mark.anyio
async def test_document_search_requires_query():
    tool = DocumentSearchTool(lambda: _FakeIndexer())
    result = await tool.execute(query="")
    assert result.success is False


@pytest.mark.anyio
async def test_document_search_returns_results():
    tool = DocumentSearchTool(lambda: _FakeIndexer())
    result = await tool.execute(query="alpha")
    assert result.success is True
    assert result.data["results"][0]["path"] == "/a.txt"


# ---- web ----

class _FakeWeb:
    async def search(self, query: str):
        return {"results": [{"title": "Alpha", "url": "https://x.com"}]}


@pytest.mark.anyio
async def test_web_search_delegates_to_provider():
    tool = WebSearchTool(_FakeWeb())
    result = await tool.execute(query="alpha ai")
    assert result.success is True
    assert result.data["results"][0]["title"] == "Alpha"


# ---- memória ----

class _FakeMemoryService:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.saved: list[dict] = []

    async def delete_memory(self, memory_id: str):
        self.deleted.append(memory_id)

    async def save_memory(self, **kwargs):
        self.saved.append(kwargs)
        return SimpleNamespace(model_dump=lambda: {"id": "m1", "content": kwargs["content"]})

    async def search_memories(self, query: str, limit: int = 5):
        return [
            SimpleNamespace(
                content=f"Procedimento {name}: passos.\n1. abrir\n2. confirmar",
                memory_type="procedimento",
                importance=1.0,
                metadata={"name": name},
            )
            for name in ("git push", "build")
        ]


@pytest.mark.anyio
async def test_memory_delete_requires_id():
    tool = MemoryDeleteTool(_FakeMemoryService())
    result = await tool.execute(memory_id="")
    assert result.success is False


@pytest.mark.anyio
async def test_memory_delete_deletes():
    service = _FakeMemoryService()
    tool = MemoryDeleteTool(service)
    result = await tool.execute(memory_id="abc")
    assert result.success is True
    assert service.deleted == ["abc"]


@pytest.mark.anyio
async def test_memory_search_returns_matches():
    tool = MemorySearchTool(_FakeMemoryService())
    result = await tool.execute(query="alpha")
    assert result.success is True


@pytest.mark.anyio
async def test_memory_save_saves():
    service = _FakeMemoryService()
    tool = MemorySaveTool(service)
    result = await tool.execute(content="fato", importance=0.9)
    assert result.success is True
    assert service.saved


@pytest.mark.anyio
async def test_procedure_save_compiles_steps():
    service = _FakeMemoryService()
    tool = ProcedureSaveTool(service)
    result = await tool.execute(name="build", description="compilar", steps=["limpar", "compilar"])
    assert result.success is True
    assert service.saved[0]["metadata"]["name"] == "build"


@pytest.mark.anyio
async def test_procedure_run_filters_by_name():
    service = _FakeMemoryService()
    tool = ProcedureRunTool(service)
    result = await tool.execute(name="git push")
    assert result.success is True
    procedures = result.data["procedures"]
    assert procedures and procedures[0]["memory_type"] == "procedimento"


# ---- tasks ----

class _FakeTaskService:
    async def create_task(self, **kwargs):
        return SimpleNamespace(__dict__={"id": "t1", "title": kwargs["title"]})

    async def execute_task(self, task_id: str):
        return SimpleNamespace(success=True, task_id=task_id, result={"ok": True}, error=None)

    async def list_tasks(self, limit: int = 50):
        return [SimpleNamespace(id="t1", title="x")]

    async def register_allowed_path(self, path: str, **kwargs):
        return SimpleNamespace(id=1, path=path, entry_type="directory", is_allowed=1)


@pytest.mark.anyio
async def test_task_create_creates():
    tool = TaskCreateTool(_FakeTaskService())
    result = await tool.execute(title="t", instruction="i", action="create_file", params={})
    assert result.success is True


@pytest.mark.anyio
async def test_task_execute_executes():
    tool = TaskExecuteTool(_FakeTaskService())
    result = await tool.execute(task_id="t1")
    assert result.success is True


@pytest.mark.anyio
async def test_task_list_lists():
    tool = TaskListTool(_FakeTaskService())
    result = await tool.execute()
    assert result.success is True


@pytest.mark.anyio
async def test_task_register_path_registers():
    tool = TaskRegisterPathTool(_FakeTaskService())
    result = await tool.execute(path="C:/projeto")
    assert result.success is True


# ---- câmera ----

@pytest.mark.anyio
async def test_camera_tool_has_schema():
    from app.skills.computer.tools.camera import DetectCameraTool

    tool = DetectCameraTool()
    assert tool.permission.value in ("write", "read", "sensitive")
    assert tool.parameters_schema()["type"] == "object"