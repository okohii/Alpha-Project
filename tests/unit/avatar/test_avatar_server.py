from __future__ import annotations

import asyncio

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.avatar.renderer import AvatarCommand
from app.avatar.server import (
    AvatarWSRenderer,
    _is_exit,
    _parse_confirmation_candidate,
    router,
)
from app.avatar.state import AvatarState
from app.security import SENSITIVE_PREFIX

app = FastAPI()
app.include_router(router)


def test_avatar_health():
    client = TestClient(app)
    response = client.get("/avatar/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "avatar"


def test_avatar_serves_ui():
    client = TestClient(app)
    response = client.get("/avatar/")
    assert response.status_code == 200
    assert b"ALPHA" in response.content


def test_avatar_serves_static_asset():
    client = TestClient(app)
    response = client.get("/avatar/ui/app.js")
    assert response.status_code == 200
    assert b"WebSocket" in response.content


def test_avatar_asset_traversal_denied():
    import asyncio

    from fastapi.responses import FileResponse

    response = asyncio.run(aread_asset("../../db/models.py"))
    assert isinstance(response, FileResponse)
    assert str(response.path).endswith("index.html")


async def aread_asset(path: str):
    from app.avatar.server import avatar_asset

    return await avatar_asset(path)


def test_parse_confirmation_candidate_action():
    parsed = _parse_confirmation_candidate(f"{SENSITIVE_PREFIX}shell_exec: dir C:\\")
    assert parsed["kind"] == "action"
    assert parsed["tool"] == "shell_exec"


def test_parse_confirmation_candidate_path():
    parsed = _parse_confirmation_candidate("C:\\Users\\guto\\Documentos")
    assert parsed["kind"] == "path"
    assert parsed["tool"] == "permissão de acesso"


def test_is_exit_words():
    assert _is_exit("sair") is True
    assert _is_exit("Sair!") is True
    assert _is_exit("encerrar") is True
    assert _is_exit("quero sair") is False
    assert _is_exit("que horas são?") is False
    assert _is_exit("") is False


async def test_avatar_ws_renderer_builds_message():
    out: asyncio.Queue[dict] = asyncio.Queue()
    renderer = AvatarWSRenderer(out)
    command = AvatarCommand(
        state=AvatarState.SPEAKING,
        animation="speaking",
        expression="neutral",
        emotion="happy",
        lip_sync=True,
    )
    renderer.show(command)
    msg = await out.get()
    assert msg["type"] == "state"
    assert msg["state"] == "speaking"
    assert msg["animation"] == "speaking"
    assert msg["emotion"] == "happy"


def test_avatar_integration_state_set_via_events():
    """A sessão (EventBus → AvatarController → renderer) deve refletir eventos.

    Simula o pipeline da UI sem tocar em microfone: emite no bus o mesmo
    fluxo do modo voz e confere que o renderer recebe as mensagens certas.
    """
    import asyncio

    from app.avatar.controller import AvatarController
    from app.core.events import EventBus, EventType

    async def _run():
        out: asyncio.Queue[dict] = asyncio.Queue()
        bus = EventBus()
        controller = AvatarController(renderer=AvatarWSRenderer(out))
        controller.subscribe(bus)
        bus.emit(EventType.assistant_listening)
        bus.emit(EventType.agent_started)
        bus.emit(EventType.tool_started)
        bus.emit(EventType.assistant_speaking, {"emotion": "calm"})
        bus.emit(EventType.agent_finished)
        controller.unsubscribe()
        messages = [await out.get() for _ in range(5)]
        return messages

    messages = asyncio.run(_run())
    states = [m["state"] for m in messages]
    assert states == ["listening", "processing", "executing", "speaking", "success"]
    assert messages[3]["emotion"] == "calm"


def test_avatar_ws_ping_pong():
    client = TestClient(app)
    with client.websocket_connect("/avatar/ws") as ws:
        ws.send_json({"action": "ping"})
        message = ws.receive_json()
        assert message["type"] == "pong"
