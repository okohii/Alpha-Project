from __future__ import annotations

from pathlib import Path

import pytest

from app.speech.pipeline import VoicePipeline
from app.speech.tts import TextToSpeechError


class STT:
    async def transcribe(self, path):
        return type("Transcription", (), {"text": "abrir navegador", "language": "pt", "segments": [], "confidence": 0.97, "is_suspicious": False})()


class TTS:
    async def synthesize(self, text, delivery=None):
        return Path("answer.wav")


class Listener:
    async def start(self): pass
    async def stop(self): pass


@pytest.mark.anyio
async def test_voice_pipeline_transcription_is_source_for_agent_boundary(tmp_path: Path):
    pipeline = VoicePipeline(listener=Listener(), stt=STT())
    result = await pipeline.process(tmp_path / "input.wav")
    assert result["transcription"] == "abrir navegador"
    assert result["confidence"] == 0.97
    assert result["is_suspicious"] is False


@pytest.mark.anyio
async def test_voice_pipeline_tts_runs_without_blocking_event_loop(monkeypatch):
    import app.speech.pipeline as module

    class Settings:
        tts_emotion_enabled = False
        tts_speed = 1.0

    monkeypatch.setattr(module, "get_settings", lambda: Settings())
    pipeline = VoicePipeline(listener=Listener(), stt=STT(), tts=TTS())
    result = await pipeline.speak("Resposta executada")
    assert result["status"] == "ok"
    assert result["audio_path"] == "answer.wav"


@pytest.mark.anyio
async def test_internal_tool_json_never_reaches_tts():
    pipeline = VoicePipeline(listener=Listener(), stt=STT(), tts=TTS())
    result = await pipeline.speak('{"tool_calls":[{"name":"open_app"}]}')
    assert result["status"] == "text_only"
    assert "bloqueado" in result["detail"]
