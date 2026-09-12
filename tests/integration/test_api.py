from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as app_main


@dataclass
class FakeConversation:
    id: str = "conv-1"
    title: str = "Nova conversa"
    created_at: datetime = datetime.now(UTC)
    updated_at: datetime = datetime.now(UTC)


class FakeQuery:
    def order_by(self, *args, **kwargs):
        return self


class FakeScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeExecuteResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return FakeScalarResult(self._items)


class FakeSession:
    def __init__(self):
        self.conversations = [FakeConversation()]

    async def execute(self, query):
        return FakeExecuteResult(self.conversations)

    async def get(self, model, conversation_id):
        return FakeConversation(id=conversation_id)

    def add(self, obj):
        self.conversations.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None


class FakeAgent:
    def __init__(self, *args, **kwargs):
        pass

    async def chat(self, message: str, conversation_id: str | None = None):
        return {
            "response": f"eco: {message}",
            "conversation_id": conversation_id or "conv-1",
            "memory_created": True,
        }


class FakeMemoryService:
    def __init__(self, *args, **kwargs):
        pass

    async def list_memories(self):
        return []

    async def save_memory(self, **kwargs):
        return type(
            "Memory",
            (),
            {"model_dump": lambda self: {"id": "m1", "content": kwargs["content"]}},
        )()

    async def delete_memory(self, memory_id: str):
        return None

    async def search_memories(self, query: str, limit: int = 5):
        return []


class FakeDocumentIndexer:
    def __init__(self, *args, **kwargs):
        pass

    async def index_allowed_directories(self):
        return {"indexed": [{"path": "/allowed/test.py", "hash": "abc", "chunks": []}]}


@pytest.mark.anyio
async def test_health_and_settings_endpoints(monkeypatch):
    monkeypatch.setattr(
        "app.services.health.checks.OllamaProvider",
        type("FakeOllama", (), {"health": lambda self: True}),
    )
    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        settings = await client.get("/settings")

    assert health.status_code == 200
    assert settings.status_code == 200


@pytest.mark.anyio
async def test_settings_reads_allowed_directories_from_db(monkeypatch):
    class FakePathRecord:
        def __init__(self, path: str):
            self.path = path
            self.is_allowed = 1

    class FakePathRepository:
        async def list(self):
            return [FakePathRecord("D:/Projects/teste agente llm")]

    monkeypatch.setattr(
        "app.api.routes_settings.ManagedPathRepository", lambda session: FakePathRepository()
    )
    monkeypatch.setattr("app.api.routes_settings.get_session", lambda: FakeSession())

    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings")

    assert response.status_code == 200
    assert "D:/Projects/teste agente llm" in response.json()["allowed_directories"]


@pytest.mark.anyio
async def test_chat_memory_and_documents_endpoints(monkeypatch):
    monkeypatch.setattr("app.runtime.application.AgentCore", FakeAgent)
    monkeypatch.setattr("app.runtime.application.MemoryRepository", lambda session: object())
    monkeypatch.setattr("app.runtime.application.MemoryService", FakeMemoryService)
    monkeypatch.setattr(
        "app.runtime.application.build_default_tool_registry",
        lambda file_manager=None, task_service=None, **kwargs: object(),
    )
    monkeypatch.setattr("app.api.routes_documents.DocumentIndexer", FakeDocumentIndexer)
    monkeypatch.setattr("app.api.routes_documents.DocumentRepository", lambda session: object())
    monkeypatch.setattr(
        "app.api.routes_documents.ManagedPathRepository",
        lambda session: type("R", (), {"list": lambda self: []})(),
    )
    monkeypatch.setattr(
        "app.api.routes_documents.FileManager",
        (lambda: type("FM", (), {"allowed_directories": []})()),
    )
    monkeypatch.setattr("app.api.routes_memory.MemoryRepository", lambda session: object())
    monkeypatch.setattr("app.api.routes_memory.MemoryService", FakeMemoryService)
    monkeypatch.setattr("app.api.routes_conversations.Conversation", FakeConversation)
    monkeypatch.setattr("app.api.routes_conversations.select", lambda *args, **kwargs: FakeQuery())
    monkeypatch.setattr("app.api.routes_conversations.get_session", lambda: FakeSession())

    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        chat = await client.post("/chat", json={"message": "Olá ALPHA."})
        memories = await client.post(
            "/memories",
            json={"content": "Meu projeto se chama Atlas.", "importance": 1.0},
        )
        documents = await client.post("/documents/index")
        conversations = await client.get("/conversations")

    assert chat.status_code == 200
    assert chat.json()["response"] == "eco: Olá ALPHA."
    assert memories.status_code == 200
    assert documents.status_code == 200
    assert conversations.status_code == 200
