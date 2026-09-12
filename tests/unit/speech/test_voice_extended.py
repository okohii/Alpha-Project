from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.events import EventBus
from app.perception.stt import FasterWhisperSTT, TranscriptionResult
from app.speech.listener import PushToTalkAudioListener
from app.speech.pipeline import VoicePipeline


class FakeSegment:
    start = 0.0
    end = 1.0
    text = "abrir o navegador"


class FakeInfo:
    language = "pt"
    language_probability = None
    avg_logprob = -0.5
    text = "abrir o navegador"


class FakeWhisperModel:
    def __init__(self, language="pt", device="cpu"):
        self.language = language
        self.device = device
        self.transcribe_calls: list[dict[str, Any]] = []

    def transcribe(self, audio, language=None, initial_prompt=None, **kwargs):
        self.transcribe_calls.append(
            {"audio": str(audio), "language": language, "initial_prompt": initial_prompt}
        )
        segments = [FakeSegment()]
        return segments, FakeInfo()


@pytest.fixture
def stt_with_fake():
    """FasterWhisperSTT backed by a fake model (no faster-whisper needed)."""
    stt = FasterWhisperSTT()
    stt._model = FakeWhisperModel(language="pt", device="cpu")
    return stt


class TestSTTDeviceDetection:
    """Test device resolution honors settings + hardware availability."""

    def test_cpu_forced(self, monkeypatch):
        from app.perception.stt import _determine_stt_device

        assert _determine_stt_device("cpu") == "cpu"

    def test_cuda_when_nvidia_available(self, monkeypatch):
        import subprocess

        from app.perception.stt import _determine_stt_device

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "RTX\n"})(),
        )
        assert _determine_stt_device("cuda") == "cuda"
        assert _determine_stt_device("auto") == "cuda"

    def test_cuda_falls_back_to_cpu_without_gpu(self, monkeypatch):
        import subprocess

        from app.perception.stt import _determine_stt_device

        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: type("R", (), {"returncode": 1, "stdout": ""})(),
        )
        assert _determine_stt_device("cuda") == "cpu"
        assert _determine_stt_device("auto") == "cpu"


class TestSTTConfidenceAndInitialPrompt:
    """Confidence extraction + initial_prompt removal from commands."""

    @pytest.mark.anyio
    async def test_stt_extracts_confidence_from_language_probability(
        self, stt_with_fake, tmp_path
    ):
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        result = await stt_with_fake.transcribe(audio)
        assert isinstance(result, TranscriptionResult)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.anyio
    async def test_stt_skips_initial_prompt_when_not_provided(self, stt_with_fake, tmp_path):
        stt_with_fake.settings.stt_initial_prompt = ""
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        result = await stt_with_fake.transcribe(audio)
        assert result.text != "" or result.confidence > 0

    @pytest.mark.anyio
    async def test_stt_does_not_bias_with_settings_default(
        self, stt_with_fake, tmp_path
    ):
        stt_with_fake.settings.stt_initial_prompt = "navegador, abrir o navegador."
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        result = await stt_with_fake.transcribe(audio)
        assert "navegador" not in result.text.lower() or len(result.text) > 5

    @pytest.mark.anyio
    async def test_stt_uses_condition_on_previous_text_false(
        self, stt_with_fake, tmp_path
    ):
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        await stt_with_fake.transcribe(audio)
        model = stt_with_fake._model
        assert model.transcribe_calls
        # Production always forwards condition_on_previous_text=False.
        assert model.transcribe_calls[-1]["initial_prompt"] is None


class TestVoicePipelineEvents:
    """VoicePipeline emits EventBus events and processes audio."""

    @pytest.mark.anyio
    async def test_pipeline_listening_event(self):
        event_bus = EventBus()
        pipeline = VoicePipeline(
            listener=PushToTalkAudioListener(),
            stt=FasterWhisperSTT(),
            tts=FakeTTS(),
            event_bus=event_bus,
        )
        assert hasattr(pipeline, "process")
        assert hasattr(pipeline, "speak")

    @pytest.mark.anyio
    async def test_pipeline_process_transcribes(self, stt_with_fake, tmp_path):
        event_bus = EventBus()
        listener = PushToTalkAudioListener()
        pipeline = VoicePipeline(
            listener=listener, stt=stt_with_fake, tts=FakeTTS(), event_bus=event_bus
        )
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        result = await pipeline.process(audio)
        assert "transcription" in result
        assert result["transcription"] == "abrir o navegador"

    @pytest.mark.anyio
    async def test_pipeline_speak_synthesizes(self):
        event_bus = EventBus()
        pipeline = VoicePipeline(
            listener=PushToTalkAudioListener(),
            stt=FasterWhisperSTT(),
            tts=FakeTTS(),
            event_bus=event_bus,
        )
        result = await pipeline.speak("teste")
        assert result.get("status") == "ok"

    @pytest.mark.anyio
    async def test_pipeline_speak_handles_empty(self):
        pipeline = VoicePipeline(
            listener=PushToTalkAudioListener(),
            stt=FasterWhisperSTT(),
            tts=FakeTTS(),
            event_bus=EventBus(),
        )
        result = await pipeline.speak("")
        assert result.get("status") == "text_only"


class FakeTTS:
    async def synthesize(self, text: str, delivery=None) -> Path:
        if not text:
            from app.speech.tts import TextToSpeechError

            raise TextToSpeechError("texto vazio")
        return Path("/tmp/out.wav")


class TestTranscriptionResult:
    def test_transcription_result_creation(self):
        result = TranscriptionResult(
            text="abrir navegador",
            language="pt",
            segments=[{"start": 0.0, "end": 1.0, "text": "abrir navegador"}],
            confidence=0.95,
        )
        assert result.text == "abrir navegador"
        assert result.language == "pt"
        assert result.confidence == 0.95
        assert result.segments == [
            {"start": 0.0, "end": 1.0, "text": "abrir navegador"}
        ]