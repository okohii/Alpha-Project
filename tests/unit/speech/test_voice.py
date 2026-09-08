from __future__ import annotations

import wave
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as app_main
from app.perception.stt import TranscriptionResult
from app.speech.listener import PushToTalkAudioListener
from app.speech.pipeline import VoicePipeline


class FakeSTT:
    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        return TranscriptionResult(
            text="olá alpha", language="pt", segments=[{"text": "olá alpha"}]
        )


class FakeTTS:
    async def synthesize(self, text: str) -> Path:
        return Path("/tmp/fake.wav")


@pytest.mark.anyio
async def test_voice_pipeline_transcribes_audio(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")
    pipeline = VoicePipeline(listener=PushToTalkAudioListener(), stt=FakeSTT(), tts=FakeTTS())

    result = await pipeline.process(audio)

    assert result["transcription"] == "olá alpha"


@pytest.mark.anyio
async def test_voice_pipeline_speaks_text_with_fallback():
    pipeline = VoicePipeline(listener=PushToTalkAudioListener(), stt=FakeSTT(), tts=FakeTTS())

    result = await pipeline.speak("Olá")

    assert result["status"] == "ok"


@pytest.mark.anyio
async def test_piper_tts_uses_library_and_creates_wav(monkeypatch, tmp_path):
    from piper import PiperVoice

    from app.speech.tts import PiperTTS

    class FakeVoice:
        def synthesize_wav(self, text, wav_file):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x00\x01\x01")

    monkeypatch.setattr(PiperVoice, "load", lambda *args, **kwargs: FakeVoice())

    tts = PiperTTS()
    tts.model_path = str(tmp_path / "voice.onnx")
    (tmp_path / "voice.onnx").write_bytes(b"fake-model")
    monkeypatch.setattr("tempfile.mkdtemp", lambda prefix="": str(tmp_path / "tts"))

    result = await tts.synthesize("teste de voz")
    assert result.exists()
    with wave.open(str(result), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 22050
        assert wav_file.getnframes() > 0


@pytest.mark.anyio
async def test_voice_routes_accept_audio_upload_and_return_transcription(monkeypatch):
    from app.api import routes_voice

    async def fake_process(self, audio_path):
        return {"transcription": "olá alpha", "language": "pt", "segments": [{"text": "olá alpha"}]}

    monkeypatch.setattr(routes_voice.VoicePipeline, "process", fake_process)

    payload = b"fake-audio"
    files = {"file": ("audio.wav", payload, "audio/wav")}

    async with AsyncClient(
        transport=ASGITransport(app=app_main.app), base_url="http://test"
    ) as client:
        response = await client.post("/voice/process", files=files)

    assert response.status_code == 200
    assert response.json()["transcription"] == "olá alpha"
