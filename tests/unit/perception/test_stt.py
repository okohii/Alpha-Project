from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


from pathlib import Path

import pytest

from app.perception.stt import FasterWhisperSTT, TranscriptionResult


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
        self.transcribe_calls = []

    def transcribe(self, audio, language=None, initial_prompt=None):
        self.transcribe_calls.append(
            {"audio": str(audio), "language": language, "initial_prompt": initial_prompt}
        )
        segments = [FakeSegment()]
        return segments, FakeInfo()


@pytest.mark.anyio
async def test_stt_passes_initial_prompt_when_configured(monkeypatch):
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()
    stt.settings.stt_initial_prompt = "navegador, abrir o navegador, Prime Video."
    monkeypatch.setattr(stt, "_load_model", lambda: model)

    result = await stt.transcribe(Path("audio.wav"))

    assert result.text == "abrir o navegador"
    assert model.calls == [
        {
            "audio": "audio.wav",
            "language": "pt",
            "initial_prompt": "navegador, abrir o navegador, Prime Video.",
        }
    ]


@pytest.mark.anyio
async def test_stt_skips_initial_prompt_when_empty(monkeypatch):
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()
    stt.settings.stt_initial_prompt = ""
    monkeypatch.setattr(stt, "_load_model", lambda: model)

    result = await stt.transcribe(Path("audio.wav"))

    assert result.text == "abrir o navegador"
    assert model.calls == [{"audio": "audio.wav", "language": "pt", "initial_prompt": None}]


@pytest.mark.anyio
async def test_stt_does_not_bias_with_initial_prompt(monkeypatch, tmp_path):
    stt = FasterWhisperSTT()
    model = FakeWhisperModel(language="pt", device="cpu")
    stt.settings.stt_initial_prompt = "navegador, abrir o navegador, Prime Video."
    monkeypatch.setattr(stt, "_load_model", lambda: model)

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    result = await stt.transcribe(audio)
    # Should not have the initial prompt bias in the transcription
    assert "navegador" not in result.text.lower() or len(result.text) > 5


@pytest.mark.anyio
async def test_stt_device_auto_selects_cuda_when_available(monkeypatch):
    stt = FasterWhisperSTT()
    stt._get_stt_device = lambda: "cuda"
    assert stt._get_stt_device() == "cuda"


@pytest.mark.anyio
async def test_stt_device_falls_back_to_cpu_when_no_gpu(monkeypatch):
    stt = FasterWhisperSTT()
    stt._get_stt_device = lambda: "cpu"
    assert stt._get_stt_device() == "cpu"


@pytest.mark.anyio
async def test_stt_effective_device_respects_settings(monkeypatch):
    """Test that _determine_stt_device works correctly with settings."""
    from app.perception.stt import _determine_stt_device

    stt = FasterWhisperSTT()

    # Test cpu forced
    stt.settings.stt_device = "cpu"
    assert _determine_stt_device("cpu") == "cpu"

    # Test cuda when gpu available (mocked)
    stt.settings.stt_device = "cuda"
    stt._get_stt_device = lambda: "cuda"
    assert _determine_stt_device("cuda") == "cuda"

    # Test auto with gpu
    stt.settings.stt_device = "auto"
    stt._get_stt_device = lambda: "cuda"
    assert _determine_stt_device("auto") == "cuda"

    # Test auto without gpu
    stt.settings.stt_device = "auto"
    stt._get_stt_device = lambda: "cpu"
    assert _determine_stt_device("auto") == "cpu"


@pytest.mark.anyio
async def test_stt_extracts_confidence_from_language_probability(monkeypatch, tmp_path):
    stt = FasterWhisperSTT()
    model = FakeWhisperModel(language="pt", device="cpu")
    original_transcribe = model.transcribe
    model.transcribe = lambda audio, language=None, initial_prompt=None: (
        [type("S", (object,), {"start": 0.0, "end": 1.0, "text": "test"})()],
        FakeInfo(),
    )
    stt._model = model

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    # Test with language_probability
    result = await stt.transcribe(audio)
    assert isinstance(result, TranscriptionResult)
    assert result.confidence >= 0.0 and result.confidence <= 1.0


@pytest.mark.anyio
async def test_stt_uses_condition_on_previous_text_false(monkeypatch, tmp_path):
    """Short commands should use condition_on_previous_text=False."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel(language="pt", device="cpu")
    call_kwargs = {}

    def mock_transcribe(audio, language=None, initial_prompt=None, **kwargs):
        call_kwargs.update(kwargs)
        return model.transcribe(audio, language, initial_prompt)

    model.transcribe = mock_transcribe
    stt._model = model

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    result = await stt.transcribe(audio, initial_prompt="test")
    # Verify condition_on_previous_text=False was in the kwargs
    assert "condition_on_previous_text" in call_kwargs
    assert call_kwargs["condition_on_previous_text"] is False


@pytest.mark.anyio
async def test_stt_detects_suspicious_transcriptions(monkeypatch, tmp_path):
    """Low confidence or very short text should flag suspicious results."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel(language="pt", device="cpu")
    stt._model = model

    # Test with very low confidence and short text
    original_transcribe = model.transcribe
    model.transcribe = lambda audio, language=None, initial_prompt=None: (
        [type("S", (object,), {"start": 0.0, "end": 1.0, "text": "a"})()],
        FakeInfo(),
    )
    stt._model = model

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    result = await stt.transcribe(audio)
    assert result.is_suspicious is True


@pytest.mark.anyio
async def test_stt_suspicious_low_confidence_short(monkeypatch, tmp_path):
    """Confidence < 0.3 and text_len < 3 should be suspicious."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel(language="pt", device="cpu")
    # Set language_probability very low
    class LowProbInfo:
        language = "pt"
        language_probability = 0.1
        avg_logprob = -2.0
        text = "a"

    model.transcribe = lambda audio, language=None, initial_prompt=None: (
        [type("S", (object,), {"start": 0.0, "end": 1.0, "text": "a"})()],
        LowProbInfo(),
    )
    stt._model = model

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    result = await stt.transcribe(audio)
    assert result.is_suspicious is True


@pytest.mark.anyio
async def test_stt_suspicious_low_confidence_medium_text(monkeypatch, tmp_path):
    """Low confidence with medium-length text should be suspicious."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel(language="pt", device="cpu")
    class MediumConfInfo:
        language = "pt"
        language_probability = 0.4
        avg_logprob = -1.0
        text = "abrir"

    model.transcribe = lambda audio, language=None, initial_prompt=None: (
        [type("S", (object,), {"start": 0.0, "end": 1.0, "text": "abrir"})()],
        MediumConfInfo(),
    )
    stt._model = model

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    result = await stt.transcribe(audio)
    assert result.is_suspicious is True


@ pytest.mark.anyio
async def test_transcription_result_creation():
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