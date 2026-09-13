from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.events import EventBus, EventType
from app.speech.cleaning import clean_for_voice
from app.speech.delivery import DeliveryProcessor, DeliveryProfile
from app.speech.emotion import EmotionController, EmotionState
from app.speech.listener import AudioListener, PushToTalkAudioListener
from app.speech.providers import get_shared_stt, get_shared_tts
from app.speech.tts import KokoroTTS, TextToSpeechError

logger = logging.getLogger("app.speech.pipeline")


def _is_internal_content(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped.startswith("{"):
        return False
    try:
        payload = json.loads(stripped)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    if "tool_calls" in payload:
        return True
    if "name" in payload and isinstance(payload["name"], str):
        if "arguments" in payload or set(payload) <= {"name", "arguments"}:
            return True
    return False


class VoicePipeline:
    def __init__(self, listener: AudioListener | None = None, stt: Any | None = None, tts: KokoroTTS | None = None, event_bus: EventBus | None = None, emotion_controller: EmotionController | None = None, delivery_processor: DeliveryProcessor | None = None) -> None:
        self.listener = listener or PushToTalkAudioListener()
        self.stt = stt
        self.tts = tts
        self.event_bus = event_bus
        self.emotion_controller = emotion_controller or EmotionController()
        self.delivery_processor = delivery_processor or DeliveryProcessor()

    def _bus(self) -> EventBus:
        return self.event_bus or EventBus()

    def _get_stt(self):
        if self.stt is None:
            self.stt = get_shared_stt()
        return self.stt

    def _get_tts(self):
        if self.tts is None:
            self.tts = get_shared_tts()
        return self.tts

    async def warmup(self, *, wake_word: bool = False, tts: bool = False) -> None:
        """Pré-carrega STT/TTS sem bloquear o caminho de escuta.

        O Kokoro usa a mesma GPU do STT/LLM e sua construção pode ser relativamente
        pesada. O TTS é aquecido em THREAD em BACKGROUND (não bloqueia o loop nem a
        prontidão da escuta): a primeira fala reutiliza o provedor cacheado.
        """
        stt = self._get_stt()
        logger.info("[voice] warmup_stt_start wake_word=%s", wake_word)
        if wake_word:
            await stt.warmup_wake()
        await stt.warmup()
        logger.info("[voice] warmup_stt_ready")
        if tts:
            logger.info("[voice] tts_warmup_background=true reason=keep_microphone_responsive")
            try:
                self._tts_warmup = asyncio.create_task(asyncio.to_thread(self._get_tts))
            except Exception:  # pragma: no cover - warmup falha não bloqueia escuta
                logger.warning("[voice] tts_warmup_task_failed", exc_info=True)

    async def _warmup_tts(self) -> None:
        # Aquecimento funcional: garante construção do TTS fora do loop.
        await asyncio.to_thread(self._get_tts)

    async def process(self, audio_path: Path) -> dict[str, Any]:
        from app.services.health.metrics import metrics, record, start_capture

        event_bus = self._bus()
        event_bus.emit(EventType.assistant_listening)
        await self.listener.start()
        try:
            event_bus.emit(EventType.assistant_transcribing)
            started_at = start_capture()
            transcription = await self._get_stt().transcribe(audio_path)
            record("stt", started_at)
            metrics.incr("alpha_stt_calls_total")
            logger.info("[voice] stt text=%r confidence=%.3f suspicious=%s language=%s segments=%d", transcription.text, transcription.confidence, transcription.is_suspicious, transcription.language, len(transcription.segments))
            return {"transcription": transcription.text, "language": transcription.language, "segments": transcription.segments, "confidence": transcription.confidence, "is_suspicious": transcription.is_suspicious}
        finally:
            await self.listener.stop()
            event_bus.emit(EventType.assistant_thinking)

    async def process_wake(self, audio_path: Path) -> dict[str, Any]:
        transcription = await self._get_stt().transcribe_wake(audio_path)
        return {
            "transcription": transcription.text,
            "language": transcription.language,
            "segments": transcription.segments,
            "confidence": transcription.confidence,
            "is_suspicious": transcription.is_suspicious,
        }

    async def speak(self, text: str) -> dict[str, Any]:
        return await self.speak_expressive(text)

    async def speak_expressive(self, text: str, *, emotion: EmotionState | None = None) -> dict[str, Any]:
        try:
            settings = get_settings()
            if _is_internal_content(text):
                logger.warning("[tts] source=internal_content_blocked len=%d", len(text))
                return {"status":"text_only","detail":"conteúdo interno bloqueado no TTS","text":text}
            prepared = clean_for_voice(text)
            if not prepared:
                logger.warning("[tts] empty_after_voice_clean source_len=%d", len(text or ""))
                return {"status":"text_only","detail":"texto sem conteúdo falável","text":text}
            logger.info("[tts] input_len=%d voice_len=%d text=%r", len(text or ""), len(prepared), prepared)
            if not settings.tts_emotion_enabled:
                state: EmotionState | None = EmotionState()
                profile: DeliveryProfile | None = None
            else:
                state = emotion if emotion is not None else self.emotion_controller.resolve(prepared)
                profile = self.emotion_controller.build_profile(state)
            event_bus = self._bus()
            event_bus.emit(EventType.assistant_speaking, {"emotion":state.emotion.value,"intensity":state.intensity,"confidence":state.confidence,"delivery":profile.to_dict() if profile is not None else None})
            tts = await asyncio.to_thread(self._get_tts)
            from app.services.health.metrics import metrics, record, start_capture

            started_at = start_capture()
            audio_path = await tts.synthesize(prepared, delivery=profile)
            record("tts", started_at)
            metrics.incr("alpha_tts_calls_total")
            logger.info("[tts] synthesized path=%s", audio_path)
            return {"audio_path":str(audio_path),"status":"ok","emotion":state.to_dict(),"delivery":profile.to_dict() if profile is not None else None,"text":prepared}
        except TextToSpeechError as exc:
            logger.exception("[tts] synthesis_failed")
            return {"status":"text_only","detail":str(exc),"text":text}

    async def speak_streaming(self, text: str, *, emotion: EmotionState | None = None):
        """Entrega arquivos WAV por segmento assim que cada um fica pronto.

        Consumidores de áudio podem iniciar o playback do primeiro chunk sem
        aguardar a geração dos seguintes. ``speak_expressive`` continua como
        API retrocompatível para quem precisa de um arquivo único.
        """
        settings = get_settings()
        if _is_internal_content(text):
            raise TextToSpeechError("conteúdo interno bloqueado no TTS")
        prepared = clean_for_voice(text)
        if not prepared:
            raise TextToSpeechError("texto sem conteúdo falável")
        if not settings.tts_emotion_enabled:
            state = EmotionState()
            profile = DeliveryProfile(speed=settings.tts_speed)
        else:
            state = emotion if emotion is not None else self.emotion_controller.resolve(prepared)
            profile = self.emotion_controller.build_profile(state)
        self._bus().emit(EventType.assistant_speaking, {"emotion":state.emotion.value,"intensity":state.intensity,"confidence":state.confidence,"delivery":profile.to_dict()})
        tts = await asyncio.to_thread(self._get_tts)
        async for path in tts.synthesize_stream(prepared, delivery=profile):
            yield {"audio_path": str(path), "emotion": state.to_dict(), "delivery": profile.to_dict(), "text": prepared}
