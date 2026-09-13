"""C1/C2 + Parte 2: gate de autorização da API (fail-closed) protege rotas sensíveis.

Regressão: tasks/macros/schedules/documents/index executavam sem qualquer
gate. Agora exigem autorização local explícita; sem token configurado a
operação é recusada (nunca 'localhost == trust').
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

import app.security.api_gate as gate
from app.security.api_gate import EXECUTE_ACTION, require_local_api_auth


def _test_client(monkeypatch, token: str) -> TestClient:
    monkeypatch.setattr(
        gate, "get_settings", lambda: SimpleNamespace(local_api_token=token)
    )

    app = FastAPI()

    @app.post("/op", dependencies=[Depends(require_local_api_auth(EXECUTE_ACTION))])
    async def op():
        return {"ok": True}

    return TestClient(app)


def test_sensitive_route_blocked_when_no_token(monkeypatch):
    client = _test_client(monkeypatch, "")
    assert client.post("/op").status_code == 403


def test_sensitive_route_blocked_with_wrong_token(monkeypatch):
    client = _test_client(monkeypatch, "secret")
    assert client.post("/op", headers={"X-Alpha-Token": "errado"}).status_code == 403
    assert client.post("/op", headers={"Authorization": "Bearer errado"}).status_code == 403


def test_sensitive_route_allowed_with_token(monkeypatch):
    client = _test_client(monkeypatch, "secret")
    assert client.post("/op", headers={"X-Alpha-Token": "secret"}).status_code == 200
    assert client.post("/op", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_sensitive_api_routes_wired_with_gate():
    from pathlib import Path

    base = Path("app/api")
    for filename in ("routes_tasks.py", "routes_macros.py", "routes_documents.py"):
        assert "require_local_api_auth" in (base / filename).read_text(encoding="utf-8")

    tasks_source = (base / "routes_tasks.py").read_text(encoding="utf-8")
    macros_source = (base / "routes_macros.py").read_text(encoding="utf-8")

    # Criação/execução/escopo exigem o gate nas rotas sensíveis.
    assert "_auth=_EXEC" in tasks_source
    assert "_auth=_EXEC" in macros_source
    # Read-only listagem permanece aberta.
    assert "async def list_tasks" in tasks_source
    assert "async def list_macros" in macros_source