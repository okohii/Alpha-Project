from __future__ import annotations

import asyncio
import logging
import struct
import threading
import wave
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.events import EventType
from app.db.session import AsyncSessionLocal
from app.interaction import InteractionManager
from app.perception.wakeword import find_wake_word, normalize, strip_wake_prefix
from app.runtime import build_agent
from app.speech import audio_io
from app.speech.cleaning import clean_markdown_artifacts
from app.speech.emotion import EmotionState
from app.speech.pipeline import VoicePipeline

logger = logging.getLogger("app.avatar.voice_runtime")
_CONFIRM_TIMEOUT = 180.0
_CONFIRM_YES = {"sim", "sima", "pode", "permitir", "permite", "confirmo", "confirmar", "ok", "okay", "certo", "pode fazer", "pode clicar"}
_CONFIRM_NO = {"nao", "não", "nega", "negar", "cancelar", "cancela", "não pode", "nao pode", "pare", "parar"}
_EXIT_WORDS = {"sair", "encerrar", "parar", "fechar"}


def is_exit(text: str) -> bool:
    return normalize(text).strip(" .,!?;:") in _EXIT_WORDS


def capture_kwargs(settings: Any) -> dict[str, Any]:
    return {
        "silence_pad": settings.stt_capture_silence_pad,
        "min_speech_duration": settings.stt_capture_min_speech_duration,
        "abs_threshold": settings.stt_capture_abs_threshold,
        "noise_floor_multiplier": settings.stt_capture_noise_floor_multiplier,
        "frame_duration": settings.stt_capture_frame_duration,
        "speech_confirm_frames": settings.stt_capture_speech_confirm_frames,
    }


def choose_after_wake(*, full_text: str, full_confidence: float, full_suspicious: bool, full_failed: bool, wake_command: str, wake_confidence: float, min_command_confidence: float) -> tuple[str, str]:
    normalized_full = (full_text or "").strip()
    if not full_failed and normalized_full and not full_suspicious and len(normalized_full.strip(" .,!?;:")) >= 2:
        return "full", normalized_full
    if wake_command and wake_confidence >= min_command_confidence:
        return "hint", wake_command
    return "skip", ""


class AvatarVoiceRuntime:
    """Runtime de voz: STT, VAD, agente, TTS, interrupção e energia.

    A sessão WebSocket fica deliberadamente fora deste componente. O runtime
    só depende de um pequeno contrato de callbacks (`push`, estado, eventos e
    cancelamento), permitindo testar voz sem abrir um WebSocket real.
    """

    def __init__(self, session: Any) -> None:
        self.session = session
        self._interruption_task: asyncio.Task[str | None] | None = None
        self._confirmation_voice_task: asyncio.Task[Any] | None = None
        self.pipeline: VoicePipeline | None = None

    async def listen_confirmation(self, pipeline: VoicePipeline) -> None:
        deadline = asyncio.get_running_loop().time() + _CONFIRM_TIMEOUT
        while not self.session.cancel_event.is_set() and asyncio.get_running_loop().time() < deadline:
            try:
                path = await asyncio.to_thread(audio_io.record_microphone_vad, max_wait=8.0, silence_pad=0.35, abort_event=self.session._audio_abort)
            except audio_io.MicrophoneRecordingError:
                return
            if path is None:
                continue
            try:
                result = await pipeline.process(path)
            except Exception:
                continue
            text = normalize(str(result.get("transcription") or "")).strip(" .,!?;:")
            if text in _CONFIRM_YES or any(text.startswith(word + " ") for word in _CONFIRM_YES):
                await self.session._confirm_queue.put(True)
                return
            if text in _CONFIRM_NO or any(text.startswith(word + " ") for word in _CONFIRM_NO):
                await self.session._confirm_queue.put(False)
                return

    async def permission_request(self, candidate: str) -> bool:
        display = self.session.parse_confirmation(candidate)
        await self.session.push({"type": "confirmation", **display})
        if self._confirmation_voice_task is not None and not self._confirmation_voice_task.done():
            self._confirmation_voice_task.cancel()
        self._confirmation_voice_task = asyncio.create_task(self.listen_confirmation(self.pipeline)) if self.pipeline else None
        try:
            return await asyncio.wait_for(self.session._confirm_queue.get(), timeout=_CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:
            return False
        finally:
            if self._confirmation_voice_task is not None and not self._confirmation_voice_task.done():
                self._confirmation_voice_task.cancel()

    async def listen_for_interruption(self, pipeline: VoicePipeline, max_wait: float, on_speech_start: Any) -> str | None:
        try:
            path = await asyncio.to_thread(audio_io.record_microphone_vad, max_wait=max(0.5, max_wait), pre_roll_duration=0.25, silence_pad=0.30, min_speech_duration=0.25, speech_confirm_frames=2, on_speech_start=on_speech_start, abort_event=self.session._interrupt_abort)
        except audio_io.MicrophoneRecordingError:
            return None
        if path is None or self.session.cancel_event.is_set() or self.session._interrupt_abort.is_set():
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

    @staticmethod
    def emotion(answer: dict[str, Any]) -> EmotionState | None:
        payload = answer.get("emotion")
        return EmotionState.from_dict(payload) if isinstance(payload, dict) else None

    async def run(self) -> None:
        settings = get_settings()
        if not settings.stt_enabled:
            await self.session.push({"type": "error", "message": "voz desativada: habilite stt_enabled"})
            return
        self.session._interaction = InteractionManager(enabled=settings.wake_word_enabled, wake_words=settings.wake_words, timeout_seconds=settings.interaction_timeout_seconds, end_words=settings.interaction_end_words)
        await self.session.push({"type": "ready", "state": self.session.state, "voice": "on", "wake_word_enabled": settings.wake_word_enabled})
        await self.session.set_interaction(not settings.wake_word_enabled, "wake_word_disabled" if not settings.wake_word_enabled else "waiting_for_wake_word")
        pipeline = VoicePipeline(event_bus=self.session.event_bus)
        self.pipeline = pipeline
        try:
            await pipeline.warmup(wake_word=settings.wake_word_enabled, tts=settings.tts_enabled)
        except Exception as exc:
            logger.exception("[avatar] voice warmup failed")
            await self.session.push({"type": "error", "message": f"falha ao preparar voz: {exc}"})
            return
        carry: str | None = None
        agent = None
        async with AsyncSessionLocal() as db_session:
            while not self.session.cancel_event.is_set():
                if self.session._interaction and self.session._interaction.expired():
                    self.session._interaction.expire()
                    await self.session.set_interaction(False, "timeout")
                text = carry
                carry = None
                if text is None:
                    self.session.event_bus.emit(EventType.assistant_listening)
                    active_before_capture = bool(self.session._interaction and self.session._interaction.active)
                    try:
                        path = await asyncio.to_thread(audio_io.record_microphone_vad, max_wait=60.0, **capture_kwargs(settings), abort_event=self.session._audio_abort)
                    except audio_io.MicrophoneRecordingError as exc:
                        await self.session.push({"type": "error", "message": f"microfone indisponível: {exc}"})
                        return
                    if path is None:
                        continue
                    if settings.wake_word_enabled and not active_before_capture:
                        try:
                            wake_result = await pipeline.process_wake(path)
                        except Exception as exc:
                            logger.exception("[avatar] wake transcription failed")
                            await self.session.push({"type": "error", "message": f"falha no detector de voz: {exc}"})
                            continue
                        wake_text = (wake_result.get("transcription") or "").strip()
                        wake_confidence = float(wake_result.get("confidence") or 0.0)
                        wake_suspicious = bool(wake_result.get("is_suspicious"))
                        wake_word = find_wake_word(wake_text, settings.wake_words)
                        if wake_word is None and wake_text and not wake_suspicious:
                            # O tiny pode derrubar/errar a wake word ("Alpha" -> "Alza",
                            # "Abro..."). A transcrição full no MESMO áudio é a fonte
                            # de verdade: só segue se ela também confirmar a palavra.
                            try:
                                full_result = await pipeline.process(path)
                            except Exception:
                                full_result = {"transcription": "", "confidence": 0.0, "is_suspicious": True}
                            full_word = find_wake_word((full_result.get("transcription") or ""), settings.wake_words)
                            if full_word is not None and not bool(full_result.get("is_suspicious")):
                                logger.info("[avatar] wake confirmed via full STT word=%r tiny_text=%r full_text=%r", full_word, wake_text, full_result.get("transcription"))
                                wake_result = full_result
                                wake_text = (full_result.get("transcription") or "").strip()
                                wake_confidence = float(full_result.get("confidence") or 0.0)
                                wake_word = full_word
                            else:
                                logger.info("[avatar] wake not found (tiny=%r full=%r) -> pedir repetição", wake_text, full_result.get("transcription"))
                                await self.session.push({"type": "caption", "from": "alpha", "text": "Pode repetir?"})
                                continue
                        if wake_suspicious or not wake_text or wake_word is None or wake_confidence < 0.30:
                            logger.debug("[avatar] wake rejected text=%r confidence=%.3f suspicious=%s", wake_text, wake_confidence, wake_suspicious)
                            continue
                        await self.session.set_interaction(True, "wake_word")
                        _, wake_command = strip_wake_prefix(wake_text, settings.wake_words)
                        wake_command = (wake_command or "").strip(" .,!?;:\n\t")
                        if not wake_command:
                            # Só o wake word foi dito: ativar a interação agora,
                            # para o próximo turno ser transcrito pelo full STT.
                            if self.session._interaction:
                                self.session._interaction.decide(wake_text)
                            continue
                        if wake_confidence >= settings.wake_command_min_confidence and not wake_suspicious:
                            text = wake_text
                        else:
                            try:
                                result = await pipeline.process(path)
                            except Exception:
                                result = {"transcription": "", "confidence": 0.0, "is_suspicious": True}
                            full_text = (result.get("transcription") or "").strip()
                            kind, _ = choose_after_wake(full_text=full_text, full_confidence=float(result.get("confidence") or 0.0), full_suspicious=bool(result.get("is_suspicious")), full_failed=False, wake_command=wake_command, wake_confidence=wake_confidence, min_command_confidence=settings.wake_command_min_confidence)
                            if kind == "skip":
                                await self.session.push({"type": "caption", "from": "alpha", "text": "Pode repetir?"})
                                continue
                            if kind == "full" and find_wake_word(full_text, settings.wake_words) is not None:
                                text = full_text
                            else:
                                text = wake_text
                    else:
                        try:
                            result = await pipeline.process(path)
                        except Exception as exc:
                            await self.session.push({"type": "error", "message": f"falha na transcrição: {exc}"})
                            continue
                        text = (result.get("transcription") or "").strip()
                        if bool(result.get("is_suspicious")) or len(normalize(text).strip(" .,!?;:") ) < 2:
                            continue
                if not text:
                    continue
                decision = self.session._interaction.decide(text) if self.session._interaction else None
                if decision is None or not decision.accepted:
                    if decision and decision.ended:
                        await self.session.push({"type": "caption", "from": "user", "text": text})
                        await self.session.set_interaction(False, "end_word")
                    continue
                if decision.activated:
                    await self.session.set_interaction(True, "wake_word")
                await self.session.push({"type": "caption", "from": "user", "text": text})
                if not decision.command:
                    continue
                if agent is None:
                    try:
                        agent = await build_agent(db_session, permission_prompt=self.permission_request, event_bus=self.session.event_bus, cancel_event=self.session.cancel_event)
                    except Exception as exc:
                        logger.exception("[avatar] agent build failed")
                        await self.session.push({"type": "error", "message": f"falha ao preparar agente: {exc}"})
                        continue
                try:
                    answer = await agent.chat(decision.command, conversation_id=self.session.conversation_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("[avatar] turno falhou")
                    await self.session.push({"type": "error", "message": f"falha no turno: {exc}"})
                    continue
                self.session.conversation_id = answer.get("conversation_id") or self.session.conversation_id
                response = clean_markdown_artifacts(answer["response"])
                await self.session.push({"type": "caption", "from": "alpha", "text": response})
                if response:
                    interrupted = await self.speak_interruptible(pipeline, response, self.emotion(answer))
                    if interrupted:
                        carry = interrupted
                        continue
                    if self.session._interaction:
                        self.session._interaction.touch_activity()
                    cooldown = max(0.0, float(getattr(settings, "avatar_post_tts_cooldown_seconds", 0.35)))
                    if cooldown > 0:
                        await self.session.push({"type": "state", "state": "cooldown", "animation": "idle", "expression": None, "emotion": None, "idle_after_ms": max(50, int(cooldown * 1000))})
                        await asyncio.sleep(cooldown)
                    if not self.session.cancel_event.is_set():
                        await self.session.push({"type": "state", "state": "listening", "animation": "idle", "expression": None, "emotion": None, "idle_after_ms": 0})

    async def speak_interruptible(self, pipeline: VoicePipeline, text: str, emotion: EmotionState | None) -> str | None:
        settings = get_settings()
        if settings.tts_streaming and hasattr(pipeline, "speak_streaming"):
            try:
                return await self.speak_interruptible_streaming(pipeline, text, emotion)
            except Exception as exc:
                logger.warning("[avatar] streaming TTS failed; fallback: %s", exc)
        return await self.speak_interruptible_single(pipeline, text, emotion)

    async def speak_interruptible_single(self, pipeline: VoicePipeline, text: str, emotion: EmotionState | None) -> str | None:
        result = await pipeline.speak_expressive(text, emotion=emotion)
        if result.get("status") != "ok":
            await self.session.push({"type": "error", "message": str(result.get("detail") or "tts indisponível")})
            return None
        audio_path = Path(result["audio_path"])
        try:
            player, frame_rate, n_frames = await asyncio.to_thread(audio_io.play_wav_async, audio_path)
        except audio_io.AudioPlaybackError as exc:
            await self.session.push({"type": "error", "message": f"áudio indisponível: {exc}"})
            return None
        duration = n_frames / frame_rate if frame_rate else 0.0
        await self.session.push({"type": "avatar_show", "animation": "speak", "duration_ms": max(320, int(duration * 1000))})
        await self.session.push({"type": "state", "state": "speaking", "animation": "speak", "expression": None, "emotion": emotion.to_dict() if emotion else None, "idle_after_ms": max(320, int(duration * 1000))})
        energy_task = asyncio.create_task(self.emit_speech_energy(audio_path))
        self.session._interrupt_abort.clear()
        playback_interrupted = threading.Event()
        def on_speech_start() -> None:
            if playback_interrupted.is_set(): return
            playback_interrupted.set()
            try: audio_io.stop_wav_async(player)
            except Exception: logger.debug("[avatar] failed to stop TTS", exc_info=True)
        self._interruption_task = asyncio.create_task(self.listen_for_interruption(pipeline, duration + 1.0, on_speech_start))
        try:
            playback_wait = asyncio.create_task(asyncio.sleep(duration + 0.25))
            done, _ = await asyncio.wait({self._interruption_task, playback_wait}, return_when=asyncio.FIRST_COMPLETED)
            if self._interruption_task in done:
                interrupted_text = self._interruption_task.result()
                if interrupted_text: return interrupted_text
                if not playback_wait.done(): await playback_wait
            else:
                try: interrupted_text = await asyncio.wait_for(self._interruption_task, timeout=0.45)
                except asyncio.TimeoutError: interrupted_text = None
                if interrupted_text: return interrupted_text
        finally:
            self.session._interrupt_abort.set()
            if self._interruption_task is not None and not self._interruption_task.done():
                self._interruption_task.cancel(); await asyncio.gather(self._interruption_task, return_exceptions=True)
            self._interruption_task = None
            energy_task.cancel()
            await asyncio.to_thread(audio_io.stop_wav_async, player)
        return None

    async def speak_interruptible_streaming(self, pipeline: VoicePipeline, text: str, emotion: EmotionState | None) -> str | None:
        playback_interrupted = threading.Event(); player: Any = None; started = False; total_duration = 0.0
        def on_speech_start() -> None:
            nonlocal player
            if playback_interrupted.is_set(): return
            playback_interrupted.set()
            try:
                if player is not None: audio_io.stop_wav_async(player)
            except Exception: logger.debug("[avatar] failed to stop streaming TTS", exc_info=True)
        self.session._interrupt_abort.clear(); self._interruption_task = None
        try:
            async for item in pipeline.speak_streaming(text, emotion=emotion):
                if playback_interrupted.is_set(): return None
                audio_path = Path(item["audio_path"])
                if not started:
                    await self.session.push({"type": "avatar_show", "animation": "speak", "duration_ms": 320})
                    await self.session.push({"type": "state", "state": "speaking", "animation": "speak", "expression": None, "emotion": emotion.to_dict() if emotion else None, "idle_after_ms": 4000})
                    started = True
                try: player, frame_rate, n_frames = await asyncio.to_thread(audio_io.play_wav_async, audio_path)
                except audio_io.AudioPlaybackError: continue
                duration = n_frames / frame_rate if frame_rate else 0.0; total_duration += duration
                self._interruption_task = asyncio.create_task(self.listen_for_interruption(pipeline, duration + 1.0, on_speech_start))
                playback_wait = asyncio.create_task(asyncio.sleep(duration + 0.25))
                done, _ = await asyncio.wait({self._interruption_task, playback_wait}, return_when=asyncio.FIRST_COMPLETED)
                if self._interruption_task in done:
                    interrupted_text = self._interruption_task.result()
                    if interrupted_text: return interrupted_text
                    if not playback_wait.done(): await playback_wait
                else:
                    try: interrupted_text = await asyncio.wait_for(self._interruption_task, timeout=0.45)
                    except asyncio.TimeoutError: interrupted_text = None
                    if interrupted_text: return interrupted_text
        finally:
            self.session._interrupt_abort.set()
            if self._interruption_task is not None and not self._interruption_task.done():
                self._interruption_task.cancel(); await asyncio.gather(self._interruption_task, return_exceptions=True)
            self._interruption_task = None
            if player is not None: await asyncio.to_thread(audio_io.stop_wav_async, player)
            await self.session.push({"type": "state", "state": "listening", "animation": "idle", "expression": None, "emotion": None, "idle_after_ms": max(320, int(total_duration * 1000))})
        return None

    async def emit_speech_energy(self, audio_path: Path) -> None:
        try:
            with wave.open(str(audio_path), "rb") as wav:
                rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels(); chunk = max(1, int(rate * 0.04))
                if width not in (1, 2, 4): return
                fmt = {1: "b", 2: "h", 4: "i"}[width]
                while not self.session.cancel_event.is_set():
                    raw = wav.readframes(chunk)
                    if not raw: break
                    sample_count = len(raw) // width; samples = struct.unpack("<" + fmt * sample_count, raw)
                    if channels > 1: samples = samples[::channels]
                    peak = max((abs(x) for x in samples), default=0); rms = (sum(x * x for x in samples) / len(samples)) ** 0.5 if samples else 0.0; max_sample = float((1 << (8 * width - 1)) - 1)
                    await self.session.queue_payload({"type": "speech_energy", "level": min(1.0, rms / max_sample * 2.2), "peak": min(1.0, peak / max_sample)})
                    await asyncio.sleep(min(0.04, max(0.01, chunk / rate)))
        except Exception:
            logger.debug("[avatar] speech energy unavailable", exc_info=True)
        finally:
            await self.session.queue_payload({"type": "speech_energy", "level": 0.0, "peak": 0.0})

    async def close(self) -> None:
        self.session._interrupt_abort.set(); self.session._audio_abort.set()
        if self._interruption_task is not None:
            self._interruption_task.cancel(); await asyncio.gather(self._interruption_task, return_exceptions=True)
        if self._confirmation_voice_task is not None:
            self._confirmation_voice_task.cancel(); await asyncio.gather(self._confirmation_voice_task, return_exceptions=True)
