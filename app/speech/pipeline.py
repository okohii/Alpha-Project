from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.events import EventBus, EventType
from app.perception.stt import FasterWhisperSTT
from app.speech.delivery import DeliveryProcessor, DeliveryProfile
from app.speech.emotion import EmotionController, EmotionState
from app.speech.listener import AudioListener, PushToTalkAudioListener
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
    def __init__(
        self,
        listener: AudioListener | None = None,
        stt: FasterWhisperSTT | None = None,
        tts: KokoroTTS | None = None,
        event_bus: EventBus | None = None,
        emotion_controller: EmotionController | None = None,
        delivery_processor: DeliveryProcessor | None = None,
    ) -> None:
        self.listener = listener or PushToTalkAudioListener()
        # Modelos ficam lazy: criar o pipeline não deve bloquear o início da escuta.
        self.stt = stt
        self.tts = tts
        self.event_bus = event_bus
        self.emotion_controller = emotion_controller or EmotionController()
        self.delivery_processor = delivery_processor or DeliveryProcessor()

    def _bus(self) -> EventBus:
        return self.event_bus or EventBus()

    def _get_stt(self) -> FasterWhisperSTT:
        if self.stt is None:
            self.stt = FasterWhisperSTT()
        return self.stt

    def _get_tts(self) -> KokoroTTS:
        if self.tts is None:
            self.tts = KokoroTTS()
        return self.tts

    async def process(self, audio_path: Path) -> dict[str, Any]:
        event_bus = self._bus()
        event_bus.emit(EventType.assistant_listening)
        await self.listener.start()
        try:
            event_bus.emit(EventType.assistant_transcribing)
            transcription = await self._get_stt().transcribe(audio_path)
            return {
                "transcription": transcription.text,
                "language": transcription.language,
                "segments": transcription.segments,
                "confidence": transcription.confidence,
                "is_suspicious": transcription.is_suspicious,
            }
        finally:
            await self.listener.stop()
            event_bus.emit(EventType.assistant_thinking)

    async def speak(self, text: str) -> dict[str, Any]:
        return await self.speak_expressive(text)

    async def speak_expressive(
        self,
        text: str,
        *,
        emotion: EmotionState | None = None,
    ) -> dict[str, Any]:
        try:
            settings = get_settings()
            prepared = self.delivery_processor.prepare(text)
            if _is_internal_content(text):
                logger.warning("[tts] source=internal_content_blocked len=%d", len(text))
                return {
                    "status": "text_only",
                    "detail": "conteúdo interno bloqueado no TTS",
                    "text": text,
                }

            if not settings.tts_emotion_enabled:
                state: EmotionState | None = EmotionState()
                profile: DeliveryProfile | None = None
            else:
                state = emotion if emotion is not None else self.emotion_controller.resolve(prepared)
                profile = self.emotion_controller.build_profile(state)

            event_bus = self._bus()
            event_bus.emit(
                EventType.assistant_speaking,
                {
                    "emotion": state.emotion.value,
                    "intensity": state.intensity,
                    "confidence": state.confidence,
                    "delivery": profile.to_dict() if profile is not None else None,
                },
            )

            audio_path = await self._get_tts().synthesize(prepared, delivery=profile)
            return {
                "audio_path": str(audio_path),
                "status": "ok",
                "emotion": state.to_dict(),
                "delivery": profile.to_dict() if profile is not None else None,
            }
        except TextToSpeechError as exc:
            return {"status": "text_only", "detail": str(exc), "text": text}
