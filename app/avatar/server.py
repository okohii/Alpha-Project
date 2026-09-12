from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.avatar.controller import AvatarController
from app.avatar.mapping import AnimationMapping
from app.avatar.renderer import AvatarCommand
from app.core.config import get_settings
from app.core.events import EventBus, EventType
from app.db.session import AsyncSessionLocal
from app.runtime import build_agent
from app.security import SENSITIVE_PREFIX
from app.speech import audio_io
from app.speech.cleaning import clean_markdown_artifacts
from app.speech.emotion import EmotionState
from app.speech.pipeline import VoicePipeline

router = APIRouter(prefix="/avatar", tags=["avatar"])
logger = logging.getLogger("app.avatar.server")

UI_DIR = Path(__file__).parent / "ui"

_CONFIRM_TIMEOUT = 180.0
_EXIT_WORDS = {"sair", "encerrar", "parar", "fechar"}


class AvatarWSRenderer:
    """Renderer que transforma cada AvatarCommand numa mensagem para a UI."""

    def __init__(self, out: asyncio.Queue[dict[str, Any]]) -> None:
        self._out = out

    def show(self, command: AvatarCommand) -> None:
        self._out.put_nowait(
            {
                "type": "state",
                "state": command.state.value,
                "animation": command.animation,
                "expression": command.expression,
                "emotion": command.emotion,
                "idle_after_ms": command.idle_after_ms,
            }
        )


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


def _is_exit(text: str) -> bool:
    cleaned = text.strip(".,!?;: ").lower()
    return cleaned in _EXIT_WORDS


class AvatarSession:
    """Sessão de voz contínua do avatar.

    O mic fica ligado por padrão. O loop é idêntico ao da CLI de voz:
    ouve → transcreve → agente responde → fala (interrompível). Apenas
    os canais de saída mudam: estados do avatar via AvatarWSRenderer e
    legendas via WebSocket, em vez de prints no terminal.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.event_bus = EventBus()
        self._out: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.avatar = AvatarController(
            renderer=AvatarWSRenderer(self._out),
            mapping=AnimationMapping(),
        )
        self.avatar.subscribe(self.event_bus)
        self._confirm_queue: asyncio.Queue[bool] = asyncio.Queue()
        self.cancel_event = asyncio.Event()
        self._voice_task: asyncio.Task[Any] | None = None
        self.conversation_id: str | None = None

    @property
    def state(self) -> str:
        return self.avatar.state.value

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

    async def permission_request(self, candidate: str) -> bool:
        """Confirmação — nunca decide sozinho; o usuário responde na UI."""
        display = _parse_confirmation_candidate(candidate)
        await self.push(
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
            elif action == "ping":
                await self.push({"type": "pong"})

    async def _start_voice(self) -> None:
        if self._voice_task is not None and not self._voice_task.done():
            return
        self._voice_task = asyncio.create_task(self._run_voice())

    async def _run_voice(self) -> None:
        settings = get_settings()
        if not (settings.stt_enabled and settings.tts_enabled):
            await self.push(
                {
                    "type": "error",
                    "message": "voz desativada: habilite stt_enabled e tts_enabled",
                }
            )
            return
        await self.push({"type": "ready", "state": self.state, "voice": "on"})
        async with AsyncSessionLocal() as session:
            agent = await build_agent(
                session,
                permission_prompt=self.permission_request,
                event_bus=self.event_bus,
                cancel_event=self.cancel_event,
            )
            pipeline = VoicePipeline(event_bus=self.event_bus)
            carry: str | None = None
            while not self.cancel_event.is_set():
                text = carry
                carry = None
                if text is None:
                    self.event_bus.emit(EventType.assistant_listening)
                    try:
                        path = await asyncio.to_thread(
                            audio_io.record_microphone_vad, max_wait=60.0
                        )
                    except audio_io.MicrophoneRecordingError as exc:
                        await self.push(
                            {"type": "error", "message": f"microfone indisponível: {exc}"}
                        )
                        return
                    if path is None:
                        continue
                    result = await pipeline.process(path)
                    text = (result.get("transcription") or "").strip()
                if not text:
                    continue
                await self.push({"type": "caption", "from": "user", "text": text})
                if _is_exit(text):
                    break
                try:
                    answer = await agent.chat(text, conversation_id=self.conversation_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("[avatar] turno falhou")
                    await self.push({"type": "error", "message": f"falha no turno: {exc}"})
                    continue
                self.conversation_id = answer.get("conversation_id") or self.conversation_id
                response = clean_markdown_artifacts(answer["response"])
                await self.push({"type": "caption", "from": "alpha", "text": response})
                if response:
                    carry = await self._speak_interruptible(
                        pipeline, response, emotion=self._emotion(answer)
                    )

    @staticmethod
    def _emotion(answer: dict[str, Any]) -> EmotionState | None:
        payload = answer.get("emotion")
        if not isinstance(payload, dict):
            return None
        return EmotionState.from_dict(payload)

    async def _speak_interruptible(
        self,
        pipeline: VoicePipeline,
        text: str,
        emotion: EmotionState | None,
    ) -> str | None:
        """Fala a resposta; interrompe assim que o usuário começa a falar."""
        result = await pipeline.speak_expressive(text, emotion=emotion)
        if result.get("status") != "ok":
            await self.push(
                {"type": "error", "message": str(result.get("detail") or "tts indisponível")}
            )
            return None
        audio_path = Path(result["audio_path"])
        try:
            player, frame_rate, n_frames = await asyncio.to_thread(
                audio_io.play_wav_async, audio_path
            )
        except audio_io.AudioPlaybackError as exc:
            await self.push({"type": "error", "message": f"áudio indisponível: {exc}"})
            return None

        speech_started = asyncio.Event()
        abort = threading.Event()
        loop = asyncio.get_running_loop()
        recorder = asyncio.create_task(self._capture_onset(pipeline, speech_started, abort, loop))
        duration = n_frames / frame_rate if frame_rate else 0.0
        playback_done = asyncio.create_task(asyncio.sleep(duration + 0.25))
        started_wait = asyncio.create_task(speech_started.wait())

        _, _ = await asyncio.wait(
            {playback_done, started_wait}, return_when=asyncio.FIRST_COMPLETED
        )
        if speech_started.is_set():
            await asyncio.to_thread(audio_io.stop_wav_async, player)
            playback_done.cancel()
            try:
                return await recorder
            except Exception:
                return None
        started_wait.cancel()
        abort.set()
        try:
            await recorder
        except Exception:
            pass
        await asyncio.to_thread(audio_io.stop_wav_async, player)
        return None

    async def _capture_onset(
        self,
        pipeline: VoicePipeline,
        speech_started: asyncio.Event,
        abort: threading.Event,
        loop: asyncio.AbstractEventLoop,
    ) -> str | None:
        """Grava durante a reprodução e transcreve o que foi dito (se houver)."""

        def _signal() -> None:
            loop.call_soon_threadsafe(speech_started.set)

        path = await asyncio.to_thread(
            audio_io.record_microphone_vad, on_speech_start=_signal, abort_event=abort
        )
        if path is None:
            return None
        result = await pipeline.process(path)
        text = (result.get("transcription") or "").strip()
        return text or None


@router.websocket("/ws")
async def avatar_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.debug("[avatar] ws connected")
    session = AvatarSession(websocket)
    pump = asyncio.create_task(session.pump())
    receive = asyncio.create_task(session.receive_loop())
    try:
        await asyncio.wait({receive, pump}, return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        session.cancel_event.set()
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


@router.get("/ui/{file_path}", include_in_schema=False)
async def avatar_asset(file_path: str) -> FileResponse:
    candidate = (UI_DIR / file_path).resolve()
    if candidate.parent != UI_DIR.resolve() or not candidate.is_file():
        return FileResponse(UI_DIR / "index.html")
    return FileResponse(candidate)
