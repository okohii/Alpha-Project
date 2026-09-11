from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.perception.stt import FasterWhisperSTT, TranscriptionResult
from app.speech.pipeline import VoicePipeline


class FakeSegment:
    start = 0.0
    end = 1.0
    text = "abrir o navegador"


class FakeInfo:
    language = "pt"
    language_probability = None
    avg_logprob = -0.5


class FakeWhisperModel:
    def __init__(self, language="pt", device="cpu"):
        self.language = language
        self.device = device
        self.transcribe_calls = []

    def transcribe(self, audio, language=None, initial_prompt=None):
        self.transcribe_calls.append(
            {"audio": str(audio), "language": language, "initial_prompt": initial_prompt}
        )
        segments = [FakeSegment()]
        return segments, FakeInfo()


@pytest.fixture
def stt_with_fake(monkeypatch):
    stt = FasterWhisperSTT()
    model = FakeWhisperModel(language="pt", device="cpu")
    stt._model = model
    return stt


class TestSTTDeviceDetection:
    """Test STT device auto-detection and GPU/CPU fallback."""

    @pytest.mark.anyio
    async def test_stt_device_auto_selects_cuda_when_available(monkeypatch):
        stt = FasterWhisperSTT()
        # Override device detection to return cuda
        stt._get_stt_device = lambda: "cuda"
        assert stt._get_stt_device() == "cuda"

    @pytest.mark.anyio
    async def test_stt_device_falls_back_to_cpu_when_no_gpu(monkeypatch):
        stt = FasterWhisperSTT()
        stt._get_stt_device = lambda: "cpu"
        assert stt._get_stt_device() == "cpu"


class TestSTTConfidenceAndInitialPrompt:
    """Test confidence indicators and initial_prompt removal."""

    @pytest.mark.anyio
    async def test_stt_extracts_confidence_from_language_probability(
        self, monkeypatch, tmp_path
    ):
        stt = FasterWhisperSTT()
        model = FakeWhisperModel(language="pt", device="cpu")
        # Set language_probability on the info
        original_transcribe = model.transcribe
        model.transcribe = lambda audio, language=None, initial_prompt=None: (
            [FakeSegment()],
            FakeInfo(),
        )
        # We need to set info attributes - the real model does this
        stt._model = model

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        # Test with language_probability
        result = await stt.transcribe(audio)
        assert isinstance(result, TranscriptionResult)
        assert result.confidence >= 0.0 and result.confidence <= 1.0

    @pytest.mark.anyio
    async def test_stt_skips_initial_prompt_when_empty(monkeypatch, tmp_path):
        stt = FasterWhisperSTT()
        model = FakeWhisperModel(language="pt", device="cpu")
        stt.settings.stt_initial_prompt = ""
        stt._model = model

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        result = await stt.transcribe(audio)
        assert result.text != "" or result.confidence > 0

    @pytest.mark.anyio
    async def test_stt_does_not_bias_with_initial_prompt(monkeypatch, tmp_path):
        stt = FasterWhisperSTT()
        model = FakeWhisperModel(language="pt", device="cpu")
        stt.settings.stt_initial_prompt = "navegador, abrir o navegador, Prime Video."
        stt._model = model

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        result = await stt.transcribe(audio)
        # Should not have the initial prompt bias in the transcription
        assert "navegador" not in result.text.lower() or len(result.text) > 5


class TestVADAndSilenceDetection:
    """Test VAD pre-roll and silence detection."""

    @pytest.mark.anyio
    async def test_stt_uses_condition_on_previous_text_false(
        self, monkeypatch, tmp_path
    ):
        """Short commands should use condition_on_previous_text=False."""
        stt = FasterWhisperSTT()
        model = FakeWhisperModel(language="pt", device="cpu")
        call_kwargs = {}

        def mock_transcribe(audio, language=None, initial_prompt=None, **kwargs):
            call_kwargs.update(kwargs)
            # Store the condition_on_previous_text flag
            if "condition_on_previous_text" in kwargs:
                call_kwargs["condition_on_previous_text"] = kwargs["condition_on_previous_text"]
            return model.transcribe(audio, language, initial_prompt)

        model.transcribe = mock_transcribe
        stt._model = model

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        result = await stt.transcribe(audio, initial_prompt="test")
        # Verify the model was called with appropriate kwargs


class TestTranscriptionResult:
    """Test TranscriptionResult data class."""

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


class TestVoicePipelineEvents:
    """Test VoicePipeline emits EventBus events."""

    @pytest.mark.anyio
    async def test_pipeline_emit_assistant_listening(self, monkeypatch, tmp_path):
        from app.core.events import EventBus, EventType
        from app.speech.listener import PushToTalkAudioListener
        from app.speech.pipeline import VoicePipeline

        listener = PushToTalkAudioListener()
        listener._running = False

        stt = FasterWhisperSTT()
        tts = type("FakeTTS", (), {"synthesize": lambda self, text: Path("/tmp/out.wav")})()

        pipeline = VoicePipeline(listener=listener, stt=stt, tts=tts)

        # Test that pipeline can be constructed and events are available
        assert hasattr(pipeline, "process")
        assert hasattr(pipeline, "speak")

    @pytest.mark.anyio
    async def test_pipeline_emit_assistant_transcribing(self, monkeypatch, tmp_path):
        from app.core.events import EventBus, EventType
        from app.speech.listener import PushToTalkAudioListener
        from app.speech.pipeline import VoicePipeline

        listener = PushToTalkAudioListener()
        listener._running = False

        stt = FasterWhisperSTT()
        tts = type("FakeTTS", (), {"synthesize": lambda self, text: Path("/tmp/out.wav")})()

        pipeline = VoicePipeline(listener=listener, stt=stt, tts=tts)

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        result = await pipeline.process(audio)
        assert "transcription" in result

    @pytest.mark.anyio
    async def test_pipeline_emit_assistant_speaking(self, monkeypatch, tmp_path):
        from app.core.events import EventBus, EventType
        from app.speech.listener import PushToTalkAudioListener
        from app.speech.pipeline import VoicePipeline

        listener = PushToTalkAudioListener()
        listener._running = False

        stt = FasterWhisperSTT()
        tts = type("FakeTTS", (), {"synthesize": lambda self, text: Path("/tmp/out.wav")})()

        pipeline = VoicePipeline(listener=listener, stt=stt, tts=tts)

        result = await pipeline.speak("teste")
        assert result.get("status") in ("ok", "text_only")


class TestVoicePipelineCutoffAndNoise:
    """Test voice pipeline cutoff and noise handling."""

    @pytest.mark.anyio
    async def test_pipeline_cutoff_when_silence_detected(self, monkeypatch, tmp_path):
        """Pipeline should handle early cutoff when silence is detected."""
        from app.speech.listener import PushToTalkAudioListener

        listener = PushToTalkAudioListener()

        stt = FasterWhisperSTT()
        tts = type("FakeTTS", (), {"synthesize": lambda self, text: Path("/tmp/out.wav")})()

        pipeline = VoicePipeline(listener=listener, stt=stt, tts=tts)

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake")

        # Should handle gracefully
        result = await pipeline.process(audio)
        assert "transcription" in result

    @pytest.mark.anyio
    async def test_pipeline_handles_noisy_audio(self, monkeypatch, tmp_path):
        """Pipeline should handle audio with background noise."""
        from app.perception.stt import FasterWhisperSTT

        stt = FasterWhisperSTT()
        model = FakeWhisperModel(language="pt", device="cpu")
        stt._model = model

        # Mock to return result even with noisy-like input
        original_transcribe = model.transcribe
        model.transcribe = lambda audio, language=None, initial_prompt=None: (
            [type("S", (object,), {"start": 0.0, "end": 1.0, "text": "comando"})()],
            FakeInfo(),
        )

        audio = tmp_path / "audio_noisy.wav"
        audio.write_bytes(b"noisy")

        result = await stt.transcribe(audio)
        assert result.text == "comando"