from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.avatar.controller import AvatarController
from app.avatar.mapping import AnimationMapping
from app.avatar.renderer import AvatarCommand
from app.avatar.voice_runtime import AvatarVoiceRuntime, capture_kwargs as _capture_kwargs, choose_after_wake as _choose_after_wake, is_exit as _is_exit
from app.core.bounded import put_dropping_oldest
from app.core.events import EventBus, EventType, SystemEvent
from app.core.presentation import confirmation_payload, execution_payload, parse_confirmation_candidate
from app.avatar.state import state_for_event
from app.db.session import AsyncSessionLocal
from app.security.wsauth import validate_websocket_connection, ws_client_host

router = APIRouter(prefix="/avatar", tags=["avatar"])
logger = logging.getLogger("app.avatar.server")
UI_DIR = Path(__file__).parent / "ui"
_EXECUTION_EVENTS = {EventType.tool_started, EventType.tool_finished, EventType.tool_failed, EventType.skill_started, EventType.skill_finished, EventType.verification_started, EventType.verification_completed, EventType.task_step_completed, EventType.task_completed, EventType.task_failed, EventType.honesty_gate, EventType.textual_tool_call_blocked}


class AvatarWSRenderer:
    """Adapter de saída: converte comandos do AvatarController em mensagens WS."""

    def __init__(self, out: asyncio.Queue[dict[str, Any]]) -> None:
        self._out = out

    def show(self, command: AvatarCommand) -> None:
        put_dropping_oldest(
            self._out,
            {"type": "state", "state": command.state.value, "animation": command.animation, "expression": command.expression, "emotion": command.emotion, "idle_after_ms": command.idle_after_ms},
        )


# Re-exports de compatibilidade com testes/consumidores antigos.
_parse_confirmation_candidate = parse_confirmation_candidate
_execution_payload = execution_payload


class AvatarSession:
    """Sessão fina de transporte/lifecycle.

    Responsabilidades deliberadamente limitadas a WebSocket, filas, estado de
    sessão e ciclo de vida. Voz/STT/VAD/TTS/interrupção/agente ficam em
    ``AvatarVoiceRuntime``; animação fica em ``AvatarController``.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.event_bus = EventBus()
        self._out: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        self.avatar = AvatarController(renderer=AvatarWSRenderer(self._out), mapping=AnimationMapping())
        self.avatar.subscribe(self.event_bus)
        self.event_bus.subscribe_all(self._forward_agent_event)
        self._confirm_queue: asyncio.Queue[bool] = asyncio.Queue()
        self.cancel_event = asyncio.Event()
        self._audio_abort = __import__("threading").Event()
        self._interrupt_abort = __import__("threading").Event()
        self._voice_task: asyncio.Task[Any] | None = None
        self.conversation_id: str | None = None
        self._interaction: Any | None = None
        self.voice = AvatarVoiceRuntime(self)

    def _out_dropped(self) -> None:
        logger.warning("[avatar] fila de saída da UI cheia: descartou eventos antigos")

    @property
    def state(self) -> str:
        return self.avatar.state.value

    def _forward_agent_event(self, event: SystemEvent) -> None:
        if event.type in _EXECUTION_EVENTS:
            put_dropping_oldest(self._out, execution_payload(event), on_drop=self._out_dropped)

    async def queue_payload(self, payload: dict[str, Any]) -> None:
        put_dropping_oldest(self._out, payload, on_drop=self._out_dropped)

    async def push(self, payload: dict[str, Any]) -> None:
        try:
            await self.websocket.send_json(payload)
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def pump(self) -> None:
        while not self.cancel_event.is_set():
            payload = await self._out.get()
            try:
                await self.websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                return

    def parse_confirmation(self, candidate: str) -> dict[str, str]:
        return parse_confirmation_candidate(candidate)

    async def permission_request(self, candidate: str) -> bool:
        return await self.voice.permission_request(candidate)

    async def receive_loop(self) -> None:
        while not self.cancel_event.is_set():
            try:
                raw = await self.websocket.receive_json()
            except (WebSocketDisconnect, RuntimeError):
                return
            action = raw.get("action")
            if action == "start":
                await self._start_voice()
            elif action == "confirm":
                await self._confirm_queue.put(bool(raw.get("approved", False)))
            elif action == "close":
                self.cancel_event.set()
                self._audio_abort.set()
                self._interrupt_abort.set()
            elif action == "ping":
                await self.push({"type": "pong"})

    async def _start_voice(self) -> None:
        if self._voice_task is not None and not self._voice_task.done():
            logger.debug("[avatar] start voice ignored: loop already running")
            return
        self._audio_abort.clear()
        self._interrupt_abort.clear()
        self._voice_task = asyncio.create_task(self.voice.run())

    async def set_interaction(self, active: bool, reason: str = "") -> None:
        await self.push({"type": "interaction", "state": "active" if active else "dormant", "reason": reason})
        if active:
            await self.push({"type": "avatar_show", "animation": "wake", "duration_ms": 320})
        else:
            await self.push({"type": "execution_clear"})
            await self.push({"type": "avatar_hide", "animation": "fade", "duration_ms": 420})


@router.websocket("/ws")
async def avatar_ws(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    client_host = ws_client_host(websocket)
    ok, reason = validate_websocket_connection(origin, client_host)
    if not ok:
        logger.warning("[avatar] ws rejeitado origin=%r host=%r motivo=%s", origin, client_host, reason)
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session = AvatarSession(websocket)
    pump = asyncio.create_task(session.pump())
    receive = asyncio.create_task(session.receive_loop())
    try:
        await asyncio.wait({receive, pump}, return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        session.cancel_event.set()
        session._audio_abort.set()
        session._interrupt_abort.set()
        await session.voice.close()
        if session._voice_task is not None:
            session._voice_task.cancel()
        for task in (receive, pump):
            task.cancel()
        await asyncio.gather(receive, pump, return_exceptions=True)
        if session._voice_task is not None:
            await asyncio.gather(session._voice_task, return_exceptions=True)


@router.get("/health")
async def avatar_health() -> dict[str, str]:
    return {"status": "ok", "service": "avatar"}


@router.get("/", include_in_schema=False)
async def avatar_index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


def _resolve_ui_asset(asset_path: str) -> Path:
    normalized = (asset_path or "").replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return UI_DIR / "index.html"
    candidate = (UI_DIR / normalized).resolve()
    if UI_DIR.resolve() not in candidate.parents or not candidate.is_file():
        return UI_DIR / "index.html"
    return candidate


@router.get("/ui/{asset_path:path}", include_in_schema=False)
async def avatar_asset(asset_path: str) -> FileResponse:
    return FileResponse(_resolve_ui_asset(asset_path))
