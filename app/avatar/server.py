from __future__ import annotations

import asyncio
import logging
import struct
import threading
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.avatar.controller import AvatarController
from app.avatar.mapping import AnimationMapping
from app.avatar.renderer import AvatarCommand
from app.core.config import get_settings
from app.core.events import EventBus, EventType, SystemEvent
from app.db.session import AsyncSessionLocal
from app.interaction import InteractionManager
from app.perception.wakeword import find_wake_word, normalize, strip_wake_prefix
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
_CONFIRM_YES = {"sim", "sima", "pode", "permitir", "permite", "confirmo", "confirmar", "ok", "okay", "certo", "pode fazer", "pode clicar"}
_CONFIRM_NO = {"nao", "não", "nega", "negar", "cancelar", "cancela", "não pode", "nao pode", "pare", "parar"}
_EXECUTION_EVENTS = {EventType.tool_started, EventType.tool_finished, EventType.tool_failed, EventType.skill_started, EventType.skill_finished, EventType.verification_started, EventType.verification_completed, EventType.task_step_completed, EventType.task_completed, EventType.task_failed, EventType.honesty_gate, EventType.textual_tool_call_blocked}
_EXIT_WORDS = {"sair", "encerrar", "parar", "fechar"}


class AvatarWSRenderer:
    def __init__(self, out: asyncio.Queue[dict[str, Any]]) -> None:
        self._out = out

    def show(self, command: AvatarCommand) -> None:
        self._out.put_nowait({"type": "state", "state": command.state.value, "animation": command.animation, "expression": command.expression, "emotion": command.emotion, "idle_after_ms": command.idle_after_ms})


def _parse_confirmation_candidate(candidate: str) -> dict[str, str]:
    if candidate.startswith(SENSITIVE_PREFIX):
        rest = candidate[len(SENSITIVE_PREFIX):]
        tool_name, sep, args = rest.partition(": ")
        return {"kind": "action", "tool": tool_name.strip() if sep else rest.strip(), "arguments": args.strip() if sep else ""}
    return {"kind": "path", "tool": "permissão de acesso", "arguments": candidate}


def _is_exit(text: str) -> bool:
    return normalize(text).strip(" .,!?;:") in _EXIT_WORDS


def _capture_kwargs(settings: Any) -> dict[str, Any]:
    """Parâmetros VAD da captura vindos da configuração (testáveis)."""
    return {
        "silence_pad": settings.stt_capture_silence_pad,
        "min_speech_duration": settings.stt_capture_min_speech_duration,
        "abs_threshold": settings.stt_capture_abs_threshold,
        "noise_floor_multiplier": settings.stt_capture_noise_floor_multiplier,
        "frame_duration": settings.stt_capture_frame_duration,
        "speech_confirm_frames": settings.stt_capture_speech_confirm_frames,
    }


def _choose_after_wake(
    *,
    full_text: str,
    full_confidence: float,
    full_suspicious: bool,
    full_failed: bool,
    wake_command: str,
    wake_confidence: float,
    min_command_confidence: float,
) -> tuple[str, str]:
    """Decide a origem do comando após o wake word, em ordem de confiança.

    ``full`` → transcrição completa (small) confiável;
    ``hint`` → comando do wake (tiny) SÓ quando a confiança do wake é forte
    (≥ ``min_command_confidence``); uma ação externa nunca é executada a
    partir de evidência fraca;
    ``skip`` → nada é executado (pede repetição).
    """
    normalized_full = (full_text or "").strip()
    if not full_failed and normalized_full and not full_suspicious:
        if len(normalized_full.strip(" .,!?;:")) >= 2:
            return "full", normalized_full
    if wake_command and wake_confidence >= min_command_confidence:
        return "hint", wake_command
    return "skip", ""


def _execution_payload(event: SystemEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    tool = payload.get("tool") or payload.get("skill") or payload.get("task_id")
    labels = {EventType.tool_started: "ferramenta executando", EventType.tool_finished: "ferramenta concluída", EventType.tool_failed: "ferramenta falhou", EventType.skill_started: "skill executando", EventType.skill_finished: "skill concluída", EventType.verification_started: "verificando", EventType.verification_completed: "verificação concluída", EventType.task_step_completed: "passo concluído", EventType.task_completed: "tarefa concluída", EventType.task_failed: "tarefa falhou", EventType.honesty_gate: "controle de evidência", EventType.textual_tool_call_blocked: "tool call bloqueada"}
    return {"type": "execution", "event": event.type.value, "label": labels.get(event.type, event.type.value), "target": str(tool or ""), "success": payload.get("success"), "duration_ms": event.duration_ms, "detail": payload.get("error") or payload.get("message") or payload.get("preview") or ""}


class AvatarSession:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.event_bus = EventBus()
        self._out: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.avatar = AvatarController(renderer=AvatarWSRenderer(self._out), mapping=AnimationMapping())
        self.avatar.subscribe(self.event_bus)
        self.event_bus.subscribe_all(self._forward_agent_event)
        self._confirm_queue: asyncio.Queue[bool] = asyncio.Queue()
        self.cancel_event = asyncio.Event()
        self._audio_abort = threading.Event()
        self._interrupt_abort = threading.Event()
        self._voice_task: asyncio.Task[Any] | None = None
        self._interruption_task: asyncio.Task[str | None] | None = None
        self.conversation_id: str | None = None
        self._interaction: InteractionManager | None = None

    @property
    def state(self) -> str:
        return self.avatar.state.value

    def _forward_agent_event(self, event: SystemEvent) -> None:
        if event.type in _EXECUTION_EVENTS:
            try:
                self._out.put_nowait(_execution_payload(event))
            except Exception:
                pass

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

    async def _listen_confirmation_voice(self, pipeline: VoicePipeline) -> None:
        deadline = asyncio.get_running_loop().time() + _CONFIRM_TIMEOUT
        while not self.cancel_event.is_set() and asyncio.get_running_loop().time() < deadline:
            try:
                path = await asyncio.to_thread(audio_io.record_microphone_vad, max_wait=8.0, silence_pad=0.35, abort_event=self._audio_abort)
            except audio_io.MicrophoneRecordingError:
                return
            if path is None:
                continue
            try:
                result = await pipeline.process(path)
            except Exception:
                continue
            text = normalize(str(result.get("transcription") or "")).strip(" .,!?;:")
            if not text:
                continue
            if text in _CONFIRM_YES or any(text.startswith(word + " ") for word in _CONFIRM_YES):
                await self._confirm_queue.put(True)
                return
            if text in _CONFIRM_NO or any(text.startswith(word + " ") for word in _CONFIRM_NO):
                await self._confirm_queue.put(False)
                return

    async def _listen_for_interruption(self, pipeline: VoicePipeline, max_wait: float, on_speech_start: Any) -> str | None:
        try:
            path = await asyncio.to_thread(audio_io.record_microphone_vad, max_wait=max(0.5, max_wait), pre_roll_duration=0.25, silence_pad=0.30, min_speech_duration=0.25, speech_confirm_frames=2, on_speech_start=on_speech_start, abort_event=self._interrupt_abort)
        except audio_io.MicrophoneRecordingError:
            return None
        if path is None or self.cancel_event.is_set() or self._interrupt_abort.is_set():
            return None
        try:
            result = await pipeline.process(path)
        except Exception:
            return None
        text = (result.get("transcription") or "").strip()
        confidence = float(result.get("confidence") or 0.0)
        suspicious = bool(result.get("is_suspicious"))
        normalized = normalize(text).strip(" .,!?;:")
        if suspicious or len(normalized) < 2:
            logger.info("[avatar] interruption rejected text=%r confidence=%.3f suspicious=%s", text, confidence, suspicious)
            return None
        return text

    async def permission_request(self, candidate: str) -> bool:
        display = _parse_confirmation_candidate(candidate)
        await self.push({"type": "confirmation", "kind": display["kind"], "tool": display["tool"], "arguments": display["arguments"]})
        if hasattr(self, "_confirmation_voice_task") and self._confirmation_voice_task is not None and not self._confirmation_voice_task.done():
            self._confirmation_voice_task.cancel()
        pipeline = getattr(self, "_pipeline", None)
        self._confirmation_voice_task = asyncio.create_task(self._listen_confirmation_voice(pipeline)) if pipeline is not None else None
        try:
            return await asyncio.wait_for(self._confirm_queue.get(), timeout=_CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:
            return False
        finally:
            task = getattr(self, "_confirmation_voice_task", None)
            if task is not None and not task.done():
                task.cancel()

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
        # Proteção de reentrada: apenas UMA task de voz por sessão. Mensagens
        # "start" repetidas (ou um segundo clique durante o processamento) não
        # criam um segundo loop nem uma segunda execução da mesma interação.
        if self._voice_task is None or self._voice_task.done():
            self._audio_abort.clear()
            self._interrupt_abort.clear()
            self._voice_task = asyncio.create_task(self._run_voice())
        else:
            logger.debug("[avatar] start voice ignored: loop already running")

    async def _set_interaction(self, active: bool, reason: str = "") -> None:
        await self.push({"type": "interaction", "state": "active" if active else "dormant", "reason": reason})
        if active:
            await self.push({"type": "avatar_show", "animation": "wake", "duration_ms": 320})
        else:
            await self.push({"type": "execution_clear"})
            await self.push({"type": "avatar_hide", "animation": "fade", "duration_ms": 420})

    async def _run_voice(self) -> None:
        settings = get_settings()
        if not settings.stt_enabled:
            await self.push({"type": "error", "message": "voz desativada: habilite stt_enabled"})
            return
        self._interaction = InteractionManager(enabled=settings.wake_word_enabled, wake_words=settings.wake_words, timeout_seconds=settings.interaction_timeout_seconds, end_words=settings.interaction_end_words)
        await self.push({"type": "ready", "state": self.state, "voice": "on", "wake_word_enabled": settings.wake_word_enabled})
        if not settings.wake_word_enabled:
            await self._set_interaction(True, "wake_word_disabled")
        else:
            await self._set_interaction(False, "waiting_for_wake_word")
        pipeline = VoicePipeline(event_bus=self.event_bus)
        self._pipeline = pipeline
        try:
            await pipeline.warmup(wake_word=settings.wake_word_enabled, tts=settings.tts_enabled)
        except Exception as exc:
            logger.exception("[avatar] voice warmup failed")
            await self.push({"type": "error", "message": f"falha ao preparar voz: {exc}"})
            return
        carry: str | None = None
        agent = None
        async with AsyncSessionLocal() as session:
            while not self.cancel_event.is_set():
                if self._interaction and self._interaction.expired():
                    self._interaction.expire()
                    await self._set_interaction(False, "timeout")
                text = carry
                carry = None
                if text is None:
                    self.event_bus.emit(EventType.assistant_listening)
                    active_before_capture = bool(self._interaction and self._interaction.active)
                    try:
                        path = await asyncio.to_thread(audio_io.record_microphone_vad, max_wait=60.0, **_capture_kwargs(settings), abort_event=self._audio_abort)
                    except audio_io.MicrophoneRecordingError as exc:
                        await self.push({"type": "error", "message": f"microfone indisponível: {exc}"})
                        return
                    if path is None:
                        continue

                    # O wake detector só tem autoridade quando a sessão está
                    # realmente dormente. Depois que ALPHA foi ativado, NÃO
                    # usamos o tiny novamente: a frase inteira vai para o
                    # small para obter a maior acurácia possível.
                    if settings.wake_word_enabled and not active_before_capture:
                        try:
                            wake_result = await pipeline.process_wake(path)
                        except Exception as exc:
                            logger.exception("[avatar] wake transcription failed")
                            await self.push({"type": "error", "message": f"falha no detector de voz: {exc}"})
                            continue
                        wake_text = (wake_result.get("transcription") or "").strip()
                        wake_confidence = float(wake_result.get("confidence") or 0.0)
                        wake_suspicious = bool(wake_result.get("is_suspicious"))
                        wake_word = find_wake_word(wake_text, settings.wake_words)
                        if wake_suspicious or not wake_text or wake_word is None or wake_confidence < 0.30:
                            logger.debug("[avatar] wake rejected text=%r confidence=%.3f suspicious=%s", wake_text, wake_confidence, wake_suspicious)
                            continue
                        await self._set_interaction(True, "wake_word")
                        _, wake_command = strip_wake_prefix(wake_text, settings.wake_words)
                        wake_command = (wake_command or "").strip(" .,!?;:\n\t")
                        logger.info("[avatar] wake accepted word=%r confidence=%.3f command_hint=%r", wake_word, wake_confidence, wake_command)
                        # Se o usuário falou apenas o wake word, aguarde o
                        # próximo turno, que será transcrito pelo small.
                        if not wake_command:
                            continue
                        # Mesmo quando existe command_hint, a maior acurácia
                        # vem da transcrição full do small, não do tiny.
                        full_failed = False
                        full_text = ""
                        full_confidence = 0.0
                        full_suspicious = True
                        try:
                            result = await pipeline.process(path)
                        except Exception:
                            full_failed = True
                            logger.exception("[avatar] full transcription failed")
                        else:
                            full_text = (result.get("transcription") or "").strip()
                            full_confidence = float(result.get("confidence") or 0.0)
                            full_suspicious = bool(result.get("is_suspicious"))
                        kind, text = _choose_after_wake(
                            full_text=full_text,
                            full_confidence=full_confidence,
                            full_suspicious=full_suspicious,
                            full_failed=full_failed,
                            wake_command=wake_command,
                            wake_confidence=wake_confidence,
                            min_command_confidence=settings.wake_command_min_confidence,
                        )
                        if kind == "skip":
                            logger.info(
                                "[avatar] command skip wake_confidence=%.3f full_confidence=%.3f reason=insufficient_confidence",
                                wake_confidence,
                                full_confidence,
                            )
                            await self.push({"type": "caption", "from": "alpha", "text": "Pode repetir?"})
                            continue
                        if kind == "hint":
                            logger.info(
                                "[avatar] command source=hint wake_confidence=%.3f command=%r",
                                wake_confidence,
                                text,
                            )
                        else:
                            logger.info(
                                "[avatar] command source=full confidence=%.3f command=%r",
                                full_confidence,
                                text,
                            )
                    else:
                        # Sessão ativa: uma única transcrição completa é a fonte
                        # de verdade para o comando do usuário.
                        try:
                            logger.debug("[avatar] active interaction -> full STT")
                            result = await pipeline.process(path)
                        except Exception as exc:
                            logger.exception("[avatar] full transcription failed")
                            await self.push({"type": "error", "message": f"falha na transcrição: {exc}"})
                            continue
                        text = (result.get("transcription") or "").strip()
                        confidence = float(result.get("confidence") or 0.0)
                        suspicious = bool(result.get("is_suspicious"))
                        normalized = normalize(text).strip(" .,!?;:")
                        if suspicious or not normalized or len(normalized) < 2:
                            logger.warning("[avatar] transcription rejected text=%r confidence=%.3f suspicious=%s", text, confidence, suspicious)
                            continue

                if not text:
                    continue
                decision = self._interaction.decide(text) if self._interaction else None
                if decision is None or not decision.accepted:
                    if decision and decision.ended:
                        await self.push({"type": "caption", "from": "user", "text": text})
                        await self._set_interaction(False, "end_word")
                    continue
                if decision.activated:
                    await self._set_interaction(True, "wake_word")
                await self.push({"type": "caption", "from": "user", "text": text})
                if not decision.command:
                    continue
                if agent is None:
                    try:
                        logger.info("[avatar] building agent after voice activation")
                        agent = await build_agent(session, permission_prompt=self.permission_request, event_bus=self.event_bus, cancel_event=self.cancel_event)
                        logger.info("[avatar] agent_ready")
                    except Exception as exc:
                        logger.exception("[avatar] agent build failed")
                        await self.push({"type": "error", "message": f"falha ao preparar agente: {exc}"})
                        continue
                try:
                    answer = await agent.chat(decision.command, conversation_id=self.conversation_id)
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
                    interrupted = await self._speak_interruptible(pipeline, response, emotion=self._emotion(answer))
                    if interrupted:
                        carry = interrupted
                        continue
                    if self._interaction:
                        self._interaction.touch_activity()
                    cooldown = max(0.0, float(getattr(settings, "avatar_post_tts_cooldown_seconds", 0.35)))
                    if cooldown > 0:
                        await self.push({"type": "state", "state": "cooldown", "animation": "idle", "expression": None, "emotion": None, "idle_after_ms": max(50, int(cooldown * 1000))})
                        try:
                            await asyncio.wait_for(asyncio.sleep(cooldown), timeout=cooldown)
                        except asyncio.TimeoutError:
                            pass
                    if not self.cancel_event.is_set():
                        await self.push({"type": "state", "state": "listening", "animation": "idle", "expression": None, "emotion": None, "idle_after_ms": 0})

    @staticmethod
    def _emotion(answer: dict[str, Any]) -> EmotionState | None:
        payload = answer.get("emotion")
        return EmotionState.from_dict(payload) if isinstance(payload, dict) else None

    async def _speak_interruptible(self, pipeline: VoicePipeline, text: str, emotion: EmotionState | None) -> str | None:
        result = await pipeline.speak_expressive(text, emotion=emotion)
        if result.get("status") != "ok":
            await self.push({"type": "error", "message": str(result.get("detail") or "tts indisponível")})
            return None
        audio_path = Path(result["audio_path"])
        try:
            player, frame_rate, n_frames = await asyncio.to_thread(audio_io.play_wav_async, audio_path)
        except audio_io.AudioPlaybackError as exc:
            await self.push({"type": "error", "message": f"áudio indisponível: {exc}"})
            return None
        duration = n_frames / frame_rate if frame_rate else 0.0
        await self.push({"type": "avatar_show", "animation": "speak", "duration_ms": max(320, int(duration * 1000))})
        await self.push({"type": "state", "state": "speaking", "animation": "speak", "expression": None, "emotion": emotion.to_dict() if emotion else None, "idle_after_ms": max(320, int(duration * 1000))})
        energy_task = asyncio.create_task(self._emit_speech_energy(audio_path))
        self._interrupt_abort.clear()
        playback_interrupted = threading.Event()

        def on_speech_start() -> None:
            if playback_interrupted.is_set():
                return
            playback_interrupted.set()
            logger.info("[avatar] user speech detected during TTS; stopping playback")
            try:
                audio_io.stop_wav_async(player)
            except Exception:
                logger.debug("[avatar] failed to stop TTS on speech start", exc_info=True)

        self._interruption_task = asyncio.create_task(self._listen_for_interruption(pipeline, duration + 1.0, on_speech_start))
        try:
            playback_wait = asyncio.create_task(asyncio.sleep(duration + 0.25))
            done, _ = await asyncio.wait({self._interruption_task, playback_wait}, return_when=asyncio.FIRST_COMPLETED)
            if self._interruption_task in done:
                interrupted_text = self._interruption_task.result()
                if interrupted_text:
                    return interrupted_text
                if not playback_wait.done():
                    await playback_wait
            else:
                try:
                    interrupted_text = await asyncio.wait_for(self._interruption_task, timeout=0.45)
                except asyncio.TimeoutError:
                    interrupted_text = None
                if interrupted_text:
                    return interrupted_text
        finally:
            self._interrupt_abort.set()
            if self._interruption_task is not None and not self._interruption_task.done():
                self._interruption_task.cancel()
                await asyncio.gather(self._interruption_task, return_exceptions=True)
            self._interruption_task = None
            energy_task.cancel()
            await asyncio.to_thread(audio_io.stop_wav_async, player)
        return None

    async def _emit_speech_energy(self, audio_path: Path) -> None:
        try:
            with wave.open(str(audio_path), "rb") as wav:
                rate = wav.getframerate()
                width = wav.getsampwidth()
                channels = wav.getnchannels()
                chunk = max(1, int(rate * 0.04))
                if width not in (1, 2, 4):
                    return
                fmt = {1: "b", 2: "h", 4: "i"}[width]
                while not self.cancel_event.is_set():
                    raw = wav.readframes(chunk)
                    if not raw:
                        break
                    sample_count = len(raw) // width
                    samples = struct.unpack("<" + fmt * sample_count, raw)
                    if channels > 1:
                        samples = samples[::channels]
                    abs_values = [abs(x) for x in samples]
                    peak = max(abs_values, default=0)
                    rms = (sum(x * x for x in samples) / len(samples)) ** 0.5 if samples else 0.0
                    max_sample = float((1 << (8 * width - 1)) - 1)
                    level = min(1.0, rms / max_sample * 2.2)
                    peak_level = min(1.0, peak / max_sample)
                    self._out.put_nowait({"type": "speech_energy", "level": level, "peak": peak_level})
                    await asyncio.sleep(min(0.04, max(0.01, chunk / rate)))
        except Exception:
            logger.debug("[avatar] speech energy indisponível", exc_info=True)
        finally:
            try:
                self._out.put_nowait({"type": "speech_energy", "level": 0.0, "peak": 0.0})
            except Exception:
                pass


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
        session._audio_abort.set()
        session._interrupt_abort.set()
        if session._voice_task is not None:
            session._voice_task.cancel()
        confirmation_task = getattr(session, "_confirmation_voice_task", None)
        if confirmation_task is not None:
            confirmation_task.cancel()
        for task in (receive, pump):
            task.cancel()
        await asyncio.gather(receive, pump, return_exceptions=True)
        if session._voice_task is not None:
            await asyncio.gather(session._voice_task, return_exceptions=True)
        if confirmation_task is not None:
            await asyncio.gather(confirmation_task, return_exceptions=True)


@router.get("/health")
async def avatar_health() -> dict[str, str]:
    return {"status": "ok", "service": "avatar"}


@router.get("/", include_in_schema=False)
async def avatar_index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


def _resolve_ui_asset(asset_path: str) -> Path:
    """Resolve um asset da UI bloqueando traversal (``..``) e caminhos fora do dir."""
    normalized = (asset_path or "").replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return UI_DIR / "index.html"
    candidate = (UI_DIR / normalized).resolve()
    if UI_DIR.resolve() not in candidate.parents or not candidate.is_file():
        return UI_DIR / "index.html"
    return candidate


@router.get("/ui/{asset_path:path}", include_in_schema=False)
async def avatar_asset(asset_path: str) -> FileResponse:
    """Serve os assets estáticos da UI (app.js, astral.js, styles.css...)."""
    return FileResponse(_resolve_ui_asset(asset_path))
