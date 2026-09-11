from __future__ import annotations

from pathlib import Path
from typing import Any

from app.perception.stt import FasterWhisperSTT
from app.core.events import EventBus, EventType
from app.speech.listener import AudioListener, PushToTalkAudioListener
from app.speech.tts import PiperTTS, TextToSpeechError


class VoicePipeline:
    def __init__(
        self,
        listener: AudioListener | None = None,
        stt: FasterWhisperSTT | None = None,
        tts: PiperTTS | None = None,
    ) -> None:
        self.listener = listener or PushToTalkAudioListener()
        self.stt = stt or FasterWhisperSTT()
        self.tts = tts or PiperTTS()

    async def process(self, audio_path: Path) -> dict[str, Any]:
        event_bus = EventBus.get_instance()
        event_bus.emit(EventType.assistant_listening)
        await self.listener.start()
        try:
            event_bus.emit(EventType.assistant_transcribing)
            transcription = await self.stt.transcribe(audio_path)
            return {
                "transcription": transcription.text,
                "language": transcription.language,
                "segments": transcription.segments,
            }
        finally:
            await self.listener.stop()
            event_bus.emit(EventType.assistant_thinking)

    async def speak(self, text: str) -> dict[str, Any]:
        try:
            event_bus = EventBus.get_instance()
            event_bus.emit(EventType.assistant_speaking)
            audio_path = await self.tts.synthesize(text)
            return {"audio_path": str(audio_path), "status": "ok"}
        except TextToSpeechError as exc:
            return {"status": "text_only", "detail": str(exc), "text": text}
