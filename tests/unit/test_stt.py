from __future__ import annotations

from pathlib import Path

import pytest

from app.speech.stt import FasterWhisperSTT


class FakeSegment:
    start = 0.0
    end = 1.0
    text = "abrir o navegador"


class FakeInfo:
    language = "pt"


class FakeWhisperModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, language=None, initial_prompt=None):
        self.calls.append({"audio": audio, "language": language, "initial_prompt": initial_prompt})
        return ([FakeSegment()], FakeInfo())


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
    stt.settings.stt_initial_prompt = "  "
    monkeypatch.setattr(stt, "_load_model", lambda: model)

    result = await stt.transcribe(Path("audio.wav"))

    assert result.text == "abrir o navegador"
    assert model.calls == [{"audio": "audio.wav", "language": "pt", "initial_prompt": None}]
