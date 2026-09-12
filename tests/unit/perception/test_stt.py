from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

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
        self.transcribe_calls: list[dict[str, Any]] = []

    def transcribe(self, audio, language=None, initial_prompt=None, **kwargs):
        self.transcribe_calls.append(
            {
                "audio": str(audio),
                "language": language,
                "initial_prompt": initial_prompt,
                **kwargs,
            }
        )
        segments = [FakeSegment()]
        return segments, FakeInfo()


class _FakeResult:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


# ── initial_prompt semantics ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_stt_passes_explicit_initial_prompt(monkeypatch):
    """Only the explicit caller-supplied initial_prompt is forwarded."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()
    stt.settings.stt_initial_prompt = "old biased prompt"
    monkeypatch.setattr(stt, "_load_model", lambda: model)

    await stt.transcribe(Path("audio.wav"), initial_prompt="navegador, abrir o navegador")

    assert len(model.transcribe_calls) == 1
    assert model.transcribe_calls[0]["initial_prompt"] == "navegador, abrir o navegador"


@pytest.mark.anyio
async def test_stt_skips_prompt_when_not_provided(monkeypatch):
    """Without explicit initial_prompt the call uses None regardless of settings."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()
    stt.settings.stt_initial_prompt = "ignore this"
    monkeypatch.setattr(stt, "_load_model", lambda: model)

    await stt.transcribe(Path("audio.wav"))

    assert model.transcribe_calls[0]["initial_prompt"] is None


@pytest.mark.anyio
async def test_stt_does_not_bias_with_settings_default(monkeypatch, tmp_path):
    """Settings default is never used, so result text stays unbiased."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()
    stt.settings.stt_initial_prompt = "biased prompt"
    monkeypatch.setattr(stt, "_load_model", lambda: model)

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    result = await stt.transcribe(audio)
    assert "biased" not in result.text.lower()


# ── device detection ────────────────────────────────────────────────────────

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
    """_determine_stt_device consults settings + nvidia-smi via subprocess."""
    from app.perception.stt import _determine_stt_device

    assert _determine_stt_device("cpu") == "cpu"

    # cuda requested, nvidia-smi succeeds
    def _fake_smi_success(*args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult(returncode=0, stdout="NVIDIA GeForce RTX 3060\n")

    monkeypatch.setattr(subprocess, "run", _fake_smi_success)
    assert _determine_stt_device("cuda") == "cuda"

    # auto with GPU
    assert _determine_stt_device("auto") == "cuda"

    # cuda requested, nvidia-smi fails (no GPU)
    def _fake_smi_fail(*args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult(returncode=1, stdout="")

    monkeypatch.setattr(subprocess, "run", _fake_smi_fail)
    assert _determine_stt_device("cuda") == "cpu"
    assert _determine_stt_device("auto") == "cpu"


# ── confidence ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_stt_extracts_confidence_from_language_probability(monkeypatch, tmp_path):
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()
    model.transcribe = lambda audio, language=None, initial_prompt=None, **kw: (
        [FakeSegment()],
        FakeInfo(),
    )
    stt._model = model

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    result = await stt.transcribe(audio)
    assert isinstance(result, TranscriptionResult)
    assert 0.0 <= result.confidence <= 1.0


# ── condition_on_previous_text ──────────────────────────────────────────────

@pytest.mark.anyio
async def test_stt_uses_condition_on_previous_text_false(monkeypatch, tmp_path):
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()
    stt._model = model

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    await stt.transcribe(audio)
    assert model.transcribe_calls[-1]["condition_on_previous_text"] is False


# ── suspicious transcription detection ──────────────────────────────────────

@pytest.mark.anyio
async def test_stt_detects_suspicious_transcriptions(monkeypatch, tmp_path):
    """Low confidence or very short text flags suspicious results."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()

    class LowInfo:
        language = "pt"
        language_probability = None
        avg_logprob = -0.5
        text = "a"

    model.transcribe = lambda audio, language=None, initial_prompt=None, **kw: (
        [type("S", (object,), {"start": 0.0, "end": 1.0, "text": "a"})()],
        LowInfo(),
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
    model = FakeWhisperModel()

    class LowProbInfo:
        language = "pt"
        language_probability = 0.1
        avg_logprob = -2.0
        text = "a"

    model.transcribe = lambda audio, language=None, initial_prompt=None, **kw: (
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
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()

    class MediumConfInfo:
        language = "pt"
        language_probability = 0.4
        avg_logprob = -1.0
        text = "abrir"

    model.transcribe = lambda audio, language=None, initial_prompt=None, **kw: (
        [type("S", (object,), {"start": 0.0, "end": 1.0, "text": "abrir"})()],
        MediumConfInfo(),
    )
    stt._model = model

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    result = await stt.transcribe(audio)
    assert result.is_suspicious is True


@pytest.mark.anyio
async def test_stt_not_suspicious_high_confidence():
    """High confidence + normal text should NOT be flagged."""
    stt = FasterWhisperSTT()
    model = FakeWhisperModel()

    class HighInfo:
        language = "pt"
        language_probability = 0.95
        avg_logprob = -0.1
        text = "abrir o navegador por favor"

    model.transcribe = lambda audio, language=None, initial_prompt=None, **kw: (
        [type("S", (object,), {"start": 0.0, "end": 1.0, "text": "abrir o navegador"})()],
        HighInfo(),
    )
    stt._model = model

    result = await stt.transcribe(Path("a.wav"))
    assert result.is_suspicious is False


# ── TranscriptionResult ─────────────────────────────────────────────────────

@pytest.mark.anyio
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
