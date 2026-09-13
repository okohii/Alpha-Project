from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.events import EventBus, EventType
from app.perception.stt import FasterWhisperSTT
from app.speech.delivery import ChunkStrategy
from app.speech.emotion import EmotionState
from app.speech.listener import PushToTalkAudioListener
from app.speech.pipeline import VoicePipeline
from app.speech.tts import TextToSpeechError


class CaptureTTS:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    async def synthesize(self, text: str, delivery=None):
        self.calls.append((text, delivery))
        if not text or not text.strip():
            raise TextToSpeechError("texto vazio")
        return Path("/tmp/out.wav")


def _pipeline(tts: CaptureTTS, event_bus: EventBus | None = None) -> VoicePipeline:
    return VoicePipeline(
        listener=PushToTalkAudioListener(),
        stt=FasterWhisperSTT(),
        tts=tts,
        event_bus=event_bus,
    )


class TestPipelineExpressivity:
    @pytest.mark.anyio
    async def test_speak_detects_emotion_and_builds_delivery(self):
        tts = CaptureTTS()
        pipeline = _pipeline(tts)

        result = await pipeline.speak("Boa! Conseguimos resolver tudo.")

        assert result["status"] == "ok"
        assert result["emotion"]["emotion"] == "happy"
        assert result["emotion"]["intensity"] > 0.5
        assert result["delivery"] is not None
        assert 1.03 <= result["delivery"]["speed"] <= 1.07
        _, delivery = tts.calls[-1]
        assert delivery is not None
        assert delivery.chunk_strategy == ChunkStrategy.standard

    @pytest.mark.anyio
    async def test_neutral_text_matches_current_behavior(self):
        tts = CaptureTTS()
        pipeline = _pipeline(tts)

        result = await pipeline.speak("O relatório está na pasta documentos.")

        assert result["emotion"] == EmotionState().to_dict()
        assert result["delivery"] is not None
        assert result["delivery"]["speed"] == get_settings().tts_speed
        assert result["delivery"]["chunk_strategy"] == "relaxed"

    @pytest.mark.anyio
    async def test_explicit_emotion_overrides_detection(self):
        tts = CaptureTTS()
        pipeline = _pipeline(tts)

        result = await pipeline.speak_expressive(
            "O relatório está na pasta documentos.",
            emotion=EmotionState(emotion="excited", intensity=1.0),
        )

        assert result["emotion"]["emotion"] == "excited"
        assert result["delivery"]["chunk_strategy"] == "paused"
        assert 1.08 <= result["delivery"]["speed"] <= 1.12

    @pytest.mark.anyio
    async def test_emotion_disabled_is_backward_compatible(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "tts_emotion_enabled", False)
        tts = CaptureTTS()
        pipeline = _pipeline(tts)

        result = await pipeline.speak("Boa! Conseguimos resolver tudo.")

        assert result["status"] == "ok"
        assert result["emotion"]["emotion"] == "neutral"
        assert result["delivery"] is None
        _, delivery = tts.calls[-1]
        assert delivery is None

    @pytest.mark.anyio
    async def test_empty_text_returns_text_only(self):
        pipeline = _pipeline(CaptureTTS())
        result = await pipeline.speak("")
        assert result["status"] == "text_only"

    @pytest.mark.anyio
    async def test_text_never_contains_tags(self):
        tts = CaptureTTS()
        pipeline = _pipeline(tts)

        await pipeline.speak("[happy] Boa! **Conseguimos** resolver tudo.")

        prepared, delivery = tts.calls[-1]
        assert "[happy]" not in prepared
        assert "**" not in prepared
        assert "Boa! Conseguimos resolver tudo." in prepared

    @pytest.mark.anyio
    async def test_event_bus_receives_emotion_payload(self):
        tts = CaptureTTS()
        event_bus = EventBus()
        pipeline = _pipeline(tts, event_bus=event_bus)

        await pipeline.speak("Boa! Conseguimos resolver tudo.")

        speaking = [e for e in event_bus.audit if e.type == EventType.assistant_speaking]
        assert speaking
        assert speaking[0].payload.get("emotion") == "happy"
        assert "intensity" in speaking[0].payload
        assert "delivery" in speaking[0].payload