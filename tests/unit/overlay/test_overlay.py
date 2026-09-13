from __future__ import annotations

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.core.events import EventBus, EventType, SystemEvent
from app.overlay.server import (
    _parse_confirmation_candidate,
    _serialize_event,
    overlay_asset,
    router,
)
from app.overlay.state import (
    TERMINAL_EVENTS,
    TEXT_EVENTS,
    TOOL_EVENTS,
    OverlayState,
    state_for_event,
)
from app.security import SENSITIVE_PREFIX

app = FastAPI()
app.include_router(router)

from fastapi.responses import FileResponse  # noqa: E402


def test_state_machine_core_flow():
    assert state_for_event(EventType.agent_started) is OverlayState.THINKING
    assert state_for_event(EventType.agent_progress) is OverlayState.PLANNING
    assert state_for_event(EventType.tool_started) is OverlayState.EXECUTING
    assert state_for_event(EventType.verification_started) is OverlayState.VERIFYING
    assert state_for_event(EventType.assistant_listening) is OverlayState.LISTENING
    assert state_for_event(EventType.assistant_speaking) is OverlayState.SPEAKING
    assert state_for_event(EventType.agent_finished) is OverlayState.IDLE
    assert state_for_event(EventType.agent_failed) is OverlayState.ERROR
    assert state_for_event(EventType.agent_cancelled) is OverlayState.IDLE


def test_state_machine_post_tool_returns_to_thinking():
    assert state_for_event(EventType.tool_finished) is OverlayState.THINKING
    assert state_for_event(EventType.tool_failed) is OverlayState.THINKING
    assert state_for_event(EventType.verification_completed) is OverlayState.THINKING


def test_state_machine_ignores_unknown():
    assert state_for_event(EventType.user_message) is None
    assert state_for_event(EventType.token_stream) is None
    assert state_for_event(EventType.memory_created) is None


def test_event_group_membership():
    assert EventType.tool_started in TOOL_EVENTS
    assert EventType.tool_finished in TOOL_EVENTS
    assert EventType.tool_failed in TOOL_EVENTS
    assert EventType.user_message in TEXT_EVENTS
    assert EventType.assistant_message in TEXT_EVENTS
    assert EventType.token_stream in TEXT_EVENTS
    assert EventType.agent_finished in TERMINAL_EVENTS
    assert EventType.agent_failed in TERMINAL_EVENTS
    assert EventType.agent_cancelled in TERMINAL_EVENTS


def test_serialize_event_propagates_payload():
    event = SystemEvent(
        type=EventType.tool_started, payload={"tool": "shell_exec", "arguments": {}}
    )
    serialized = _serialize_event(event)
    assert serialized["event"] == "tool_started"
    assert serialized["payload"]["tool"] == "shell_exec"
    assert serialized["duration_ms"] is None


def test_parse_confirmation_candidate_action():
    parsed = _parse_confirmation_candidate(
        f"{SENSITIVE_PREFIX}shell_exec: dir C:\\"
    )
    assert parsed["kind"] == "action"
    assert parsed["tool"] == "shell_exec"
    assert parsed["arguments"] == "dir C:\\"


def test_parse_confirmation_candidate_path():
    parsed = _parse_confirmation_candidate("C:\\Users\\guto\\Documentos")
    assert parsed["kind"] == "path"
    assert parsed["tool"] == "permissão de acesso"
    assert parsed["arguments"] == "C:\\Users\\guto\\Documentos"


def test_overlay_health():
    client = TestClient(app)
    response = client.get("/overlay/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_overlay_serves_ui():
    client = TestClient(app)
    response = client.get("/overlay/")
    assert response.status_code == 200
    assert b"ALPHA" in response.content


def test_overlay_serves_static_asset():
    client = TestClient(app)
    response = client.get("/overlay/ui/app.js")
    assert response.status_code == 200
    assert b"WebSocket" in response.content


def test_overlay_asset_traversal_denied():
    response = run_asset("../../db/models.py")
    assert isinstance(response, FileResponse)
    assert str(response.path).endswith("index.html")  # cai no index, não vaza arquivo


def run_asset(path: str) -> FileResponse:
    import asyncio

    return asyncio.run(overlay_asset(path))


def test_ws_voice_without_audio_returns_error():
    client = TestClient(app)
    with client.websocket_connect(
        "/overlay/ws", headers={"origin": "http://127.0.0.1:18080"}
    ) as ws:
        ws.send_json({"action": "voice", "audio_base64": ""})
        message = ws.receive_json()
        assert message["type"] == "error"


def test_ws_rejects_foreign_origin():
    import pytest as _pytest
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(app)
    with _pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/overlay/ws", headers={"origin": "http://evil.example.com"}
        ):
            pass


def test_ws_rejects_null_origin():
    import pytest as _pytest
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(app)
    with _pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/overlay/ws", headers={"origin": "null"}
        ):
            pass


def test_event_bus_forward_and_state():
    """O bus da sessão converte eventos em state/done e propaga apenas o visível."""
    from app.overlay.server import _serialize_event

    bus = EventBus()
    states: list[str | None] = []
    events: list[str] = []

    def forward(event: SystemEvent) -> None:
        new_state = state_for_event(event.type)
        states.append(new_state.value if new_state else None)
        if (
            event.type in TOOL_EVENTS
            or event.type in TEXT_EVENTS
            or event.type is EventType.waiting_confirmation
        ):
            events.append(_serialize_event(event)["event"])

    unsub = bus.subscribe_all(forward)
    bus.emit(EventType.agent_started)
    bus.emit(EventType.tool_started, {"tool": "shell_exec"})
    bus.emit(EventType.agent_finished)
    unsub()
    bus.emit(EventType.tool_started)

    assert states[:3] == ["thinking", "executing", "idle"]
    assert events == ["tool_started"]
    assert len(states) == 3  # após unsubscribe não recebe mais eventos