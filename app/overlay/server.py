from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.core.events import EventBus, EventType, SystemEvent
from app.db.session import AsyncSessionLocal
from app.overlay.state import (
    TERMINAL_EVENTS,
    TEXT_EVENTS,
    TOOL_EVENTS,
    OverlayState,
    state_for_event,
)
from app.runtime import build_agent
from app.security import SENSITIVE_PREFIX
from app.speech.pipeline import VoicePipeline

router = APIRouter(prefix="/overlay", tags=["overlay"])
logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent / "ui"

_CONFIRM_TIMEOUT = 180.0
_EXECUTION_EVENTS = {
    EventType.tool_selected,
    EventType.tool_started,
    EventType.tool_finished,
    EventType.tool_failed,
    EventType.skill_started,
    EventType.skill_finished,
    EventType.verification_started,
    EventType.verification_completed,
    EventType.task_created,
    EventType.task_step_completed,
    EventType.task_completed,
    EventType.task_failed,
    EventType.honesty_gate,
    EventType.textual_tool_call_blocked,
}


def _serialize_event(event: SystemEvent) -> dict[str, Any]:
    return {
        "event": event.type.value,
        "payload": dict(event.payload or {}),
        "duration_ms": event.duration_ms,
    }


def _execution_payload(event: SystemEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    target = payload.get("tool") or payload.get("skill") or payload.get("task_id") or ""
    labels = {
        EventType.tool_selected: "ferramenta selecionada",
        EventType.tool_started: "ferramenta executando",
        EventType.tool_finished: "ferramenta concluída",
        EventType.tool_failed: "ferramenta falhou",
        EventType.skill_started: "skill iniciada",
        EventType.skill_finished: "skill concluída",
        EventType.verification_started: "verificação iniciada",
        EventType.verification_completed: "verificação concluída",
        EventType.task_created: "tarefa criada",
        EventType.task_step_completed: "passo concluído",
        EventType.task_completed: "tarefa concluída",
        EventType.task_failed: "tarefa falhou",
        EventType.honesty_gate: "honesty gate",
        EventType.textual_tool_call_blocked: "tool call textual bloqueada",
    }
    return {
        "type": "execution",
        "event": event.type.value,
        "label": labels.get(event.type, event.type.value),
        "target": str(target),
        "success": payload.get("success"),
        "duration_ms": event.duration_ms,
        "detail": payload.get("error") or payload.get("message") or payload.get("preview") or "",
    }


def _text_payload(event: SystemEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    text = payload.get("content") or payload.get("text") or payload.get("preview") or ""
    return {
        "type": "caption",
        "from": "user" if event.type is EventType.user_message else "assistant",
        "text": str(text),
        "event": event.type.value,
    }


def _parse_confirmation_candidate(candidate: str) -> dict[str, str]:
    """Extrai tool + argumentos legíveis de um candidate de confirmação."""
    if candidate.startswith(SENSITIVE_PREFIX):
        rest = candidate[len(SENSITIVE_PREFIX) :]
        tool_name, sep, args = rest.partition(": ")
        return {
            "kind": "action",
            "tool": tool_name.strip() if sep else rest.strip(),
            "arguments": args.strip() if sep else "",
        }
    return {"kind": "path", "tool": "permissão de acesso", "arguments": candidate}


class _OverlaySession:
    """Estado de uma sessão de overlay conectada via WebSocket.

    O overlay é APENAS uma interface: não decide fluxo nem segurança.
    Segurança permanece integralmente no ``AgentCore`` (o handler de
    confirmação apenas repassa a decisão do usuário).
    """

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.event_bus = EventBus()
        self.cancel_event = asyncio.Event()
        self._confirm_queue: asyncio.Queue[bool] = asyncio.Queue()
        self._event_queue: asyncio.Queue[SystemEvent] = asyncio.Queue()
        self._unsubscribe: Any | None = None
        self.conversation_id: str | None = None
        self.chat_task: asyncio.Task[Any] | None = None
        self.state = OverlayState.IDLE

    async def send(self, payload: dict[str, Any]) -> None:
        try:
            await self.websocket.send_json(payload)
        except (WebSocketDisconnect, RuntimeError):
            pass

    def _forward_event(self, event: SystemEvent) -> None:
        try:
            self._event_queue.put_nowait(event)
        except Exception:  # noqa: BLE001 - fila unbounded nunca enche
            pass

    async def _pump_events(self) -> None:
        """Converte SystemEvents em mensagens, aplicando a máquina de estados."""
        while True:
            event: SystemEvent = await self._event_queue.get()
            cid = (event.payload or {}).get("conversation_id")
            if cid and self.conversation_id != cid:
                self.conversation_id = cid

            new_state = state_for_event(event.type)
            if new_state is not None and new_state != self.state:
                self.state = new_state
                await self.send({"type": "state", "state": new_state.value})

            if event.type in _EXECUTION_EVENTS:
                await self.send(_execution_payload(event))
            if event.type in TOOL_EVENTS or (
                event.type in TEXT_EVENTS and event.type is not EventType.user_message
            ):
                if event.type in TEXT_EVENTS:
                    await self.send(_text_payload(event))
                else:
                    await self.send(_serialize_event(event))
            elif event.type is EventType.user_message:
                await self.send(_text_payload(event))
            elif event.type is EventType.memory_created:
                await self.send(_serialize_event(event))
            elif event.type in TERMINAL_EVENTS:
                await self.send(
                    {"type": "done", "event": event.type.value, "conversation_id": cid}
                )

    async def permission_request(self, candidate: str) -> bool:
        display = _parse_confirmation_candidate(candidate)
        await self.send(
            {
                "type": "confirmation",
                "kind": display["kind"],
                "tool": display["tool"],
                "arguments": display["arguments"],
            }
        )
        try:
            return await asyncio.wait_for(self._confirm_queue.get(), timeout=_CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:
            return False


async def _handle_chat(
    session: Any,
    overlay: _OverlaySession,
    message: str,
    stream: bool,
) -> None:
    agent = await build_agent(
        session,
        permission_prompt=overlay.permission_request,
        event_bus=overlay.event_bus,
        cancel_event=overlay.cancel_event,
    )
    if stream:
        async for _ in agent.chat_stream(message, conversation_id=overlay.conversation_id):
            pass
    else:
        result = await agent.chat(message, conversation_id=overlay.conversation_id)
        if result and result.get("conversation_id"):
            overlay.conversation_id = result["conversation_id"]
        return


async def _handle_voice(overlay: _OverlaySession, raw: dict[str, Any]) -> None:
    """Recebe áudio base64 e transcreve usando o EventBus da sessão."""
    audio_b64 = raw.get("audio_base64", "")
    if not audio_b64:
        await overlay.send({"type": "error", "message": "nenhum áudio recebido para transcrição"})
        return
    try:
        audio_bytes = base64.b64decode(audio_b64)
        with tempfile.TemporaryDirectory(prefix="alpha-overlay-voice-") as tmp:
            path = Path(tmp) / "voice.wav"
            path.write_bytes(audio_bytes)
            pipeline = VoicePipeline(event_bus=overlay.event_bus)
            result = await asyncio.wait_for(pipeline.process(path), timeout=120.0)
        await overlay.send(
            {
                "type": "transcription",
                "text": result.get("transcription", ""),
                "language": result.get("language", ""),
            }
        )
    except Exception as exc:  # noqa: BLE001 - mensagem de erro amigável
        await overlay.send({"type": "error", "message": f"falha ao transcrever: {exc}"})


@router.websocket("/ws")
async def overlay_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.debug("[OVERLAY] backend connected")
    overlay = _OverlaySession(websocket)
    session_ctx = AsyncSessionLocal()
    session = await session_ctx.__aenter__()
    try:
        overlay._unsubscribe = overlay.event_bus.subscribe_all(overlay._forward_event)
        pump = asyncio.create_task(overlay._pump_events())

        try:
            while True:
                raw = await websocket.receive_json()
                action = raw.get("action")
                if action in ("chat", "chat_stream"):
                    message = str(raw.get("message", "")).strip()
                    if not message:
                        continue
                    if raw.get("conversation_id"):
                        overlay.conversation_id = str(raw["conversation_id"])
                    overlay.cancel_event.clear()
                    if overlay.chat_task is not None and not overlay.chat_task.done():
                        overlay.cancel_event.set()
                        try:
                            await overlay.chat_task
                        except Exception:
                            pass
                    overlay.chat_task = asyncio.create_task(
                        _handle_chat(session, overlay, message, action == "chat_stream")
                    )
                elif action == "cancel":
                    overlay.cancel_event.set()
                elif action == "confirm":
                    await overlay._confirm_queue.put(bool(raw.get("approved", False)))
                elif action == "voice":
                    await _handle_voice(overlay, raw)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pump.cancel()
            if overlay.chat_task is not None:
                overlay.cancel_event.set()
                try:
                    await overlay.chat_task
                except Exception:
                    pass
            if overlay._unsubscribe is not None:
                overlay._unsubscribe()
    finally:
        await session_ctx.__aexit__(None, None, None)


@router.get("/health")
async def overlay_health() -> dict[str, str]:
    return {"status": "ok", "service": "overlay"}


@router.get("/", include_in_schema=False)
async def overlay_index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@router.get("/ui/{file_path}", include_in_schema=False)
async def overlay_asset(file_path: str) -> FileResponse:
    candidate = (UI_DIR / file_path).resolve()
    if candidate.parent != UI_DIR.resolve() or not candidate.is_file():
        return FileResponse(UI_DIR / "index.html")
    return FileResponse(candidate)
