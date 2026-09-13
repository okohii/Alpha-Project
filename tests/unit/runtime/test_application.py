from __future__ import annotations

import pytest

import app.runtime.application as application_module


class FakeRecord:
    def __init__(self, path: str, is_allowed: int = 1) -> None:
        self.path = path
        self.is_allowed = is_allowed


class FakeManagedPathRepository:
    def __init__(self, records=None) -> None:
        self.records = records or []
        self.registered: list[tuple] = []

    async def list(self):
        return list(self.records)

    async def register_allowed_path(self, path, entry_type, source):
        self.registered.append((path, entry_type, source))
        return FakeRecord(path)


class FakeTaskExecutorService:
    def __init__(self, managed_path_repository) -> None:
        self.managed_path_repository = managed_path_repository

    async def register_allowed_path(self, path, entry_type, source):
        return await self.managed_path_repository.register_allowed_path(
            path, entry_type, source
        )


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_build_agent(monkeypatch, repo, task_service):
    monkeypatch.setattr(
        application_module, "ManagedPathRepository", lambda session: repo
    )
    monkeypatch.setattr(
        application_module, "TaskExecutorService", lambda **kw: task_service
    )
    monkeypatch.setattr(
        application_module, "build_default_tool_registry", lambda **kw: object()
    )


@pytest.mark.anyio
async def test_sensitive_confirmation_does_not_pollute_allowed_directories(monkeypatch):
    """Confirmação de tool sensível (com SENSITIVE_PREFIX) NÃO adiciona diretório ao whitelist."""
    from app.security import SENSITIVE_PREFIX

    granted: list[str] = []

    async def permission_prompt(candidate: str) -> bool:
        granted.append(candidate)
        return True

    repo = FakeManagedPathRepository()
    task_service = FakeTaskExecutorService(repo)
    _patch_build_agent(monkeypatch, repo, task_service)

    agent = await application_module.build_agent(
        FakeSession(), permission_prompt=permission_prompt
    )

    handler = agent.permission_request_handler
    assert handler is not None

    result = await handler(f'{SENSITIVE_PREFIX}run_code: {{"code": "print(1)"}}')

    assert result is True
    # O prefixo é removido antes de exibir: a interface vê a confirmação limpa.
    assert granted == ['run_code: {"code": "print(1)"}']
    # Nenhum path derivado de tool args foi persistido no banco.
    assert repo.registered == []


@pytest.mark.anyio
async def test_real_path_permission_grant_is_memory_only(monkeypatch):
    """H7/Parte 19: confirmação de UM path não vira permissão permanente.

    O grant é adicionado APENAS em memória (escopo do agente) e NÃO é
    persistido no banco como allowlist global.
    """
    granted: list[str] = []

    async def permission_prompt(candidate: str) -> bool:
        granted.append(candidate)
        return True

    repo = FakeManagedPathRepository()
    task_service = FakeTaskExecutorService(repo)
    _patch_build_agent(monkeypatch, repo, task_service)

    agent = await application_module.build_agent(
        FakeSession(), permission_prompt=permission_prompt
    )

    handler = agent.permission_request_handler
    assert handler is not None

    candidate = "C:/Users/teste/Downloads"
    result = await handler(candidate)

    assert result is True
    assert granted == [candidate]
    # NADA foi persistido; o grant ficou em memória.
    assert repo.registered == []


@pytest.mark.anyio
async def test_denied_permission_not_registered(monkeypatch):
    """Permissão negada não registra nada (path nem tool args)."""
    granted: list[str] = []

    async def permission_prompt(candidate: str) -> bool:
        granted.append(candidate)
        return False

    repo = FakeManagedPathRepository()
    task_service = FakeTaskExecutorService(repo)
    _patch_build_agent(monkeypatch, repo, task_service)

    agent = await application_module.build_agent(
        FakeSession(), permission_prompt=permission_prompt
    )

    handler = agent.permission_request_handler
    assert handler is not None

    result = await handler("C:/Users/foo/Downloads")

    assert result is False
    assert repo.registered == []