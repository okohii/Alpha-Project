from __future__ import annotations

import asyncio

import pytest

from app.perception.stt import FasterWhisperSTT
from app.perception.wakeword import find_wake_word, strip_wake_word


def test_wake_word_normalization_accepts_alpha_and_alfa():
    assert find_wake_word("ALFA abra o navegador", "alpha") == "alfa"
    found, remainder = strip_wake_word("Alpha, abra o GitHub", "alpha")
    assert found is True
    assert remainder == "abra o github"


@pytest.mark.anyio
async def test_stt_transcription_api_is_async():
    stt = object.__new__(FasterWhisperSTT)
    assert asyncio.iscoroutinefunction(stt.transcribe)
    assert asyncio.iscoroutinefunction(stt.transcribe_wake)
    assert asyncio.iscoroutinefunction(stt.warmup)
    assert asyncio.iscoroutinefunction(stt.warmup_wake)
