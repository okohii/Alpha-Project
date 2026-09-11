from __future__ import annotations

from typing import Callable

import pytest
from pathlib import Path
from unittest.mock import patch

from app.speech.tts import KokoroTTS, PiperTTS, TextToSpeechError


class TestKokoroTTS:
    """Test Kokoro TTS integration."""

    @pytest.mark.anyio
    async def test_kokoro_synthesize_raises_without_kokoro(
        self, monkeypatch
    ):
        """Synthesize raises TextToSpeechError if kokoro-ml is not available."""
        from unittest.mock import patch

        stt = KokoroTTS()
        with patch("app.speech.tts.KokoroVoice", side_effect=ImportError):
            with pytest.raises(TextToSpeechError, match="Kokoro TTS nao disponivel"):
                await stt.synthesize("teste")

    @pytest.mark.anyio
    async def test_kokoro_synthesize_success(monkeypatch, tmp_path):
        """Synthesize successfully creates a WAV file."""
        stt = KokoroTTS()

        # Mock KokoroVoice
        class MockKokoroVoice:
            def __init__(self, *args, **kwargs):
                pass

            def synthesize(self, text):
                # Return fake audio bytes (16-bit PCM)
                import struct
                return struct.pack("<" + "h" * 1000, *range(1000))

            def stream_synthesize(self, text):
                yield b"\x00" * 1000

        with patch(
            "app.speech.tts.KokoroVoice", MockKokoroVoice
        ):
            result = await stt.synthesize("teste")
            assert Path(result).exists()
            assert result.endswith(".wav")


class TestPiperTTS:
    """Test Piper TTS preservation."""

    def test_piper_tts_has_synthesize(self):
        """PiperTTS class has synthesize method."""
        tts = PiperTTS()
        assert hasattr(tts, "synthesize")

    def test_piper_tts_is_text_to_speech(self):
        """PiperTTS implements TextToSpeech interface."""
        from app.speech.tts import TextToSpeech
        tts = PiperTTS()
        assert isinstance(tts, TextToSpeech)


class TestTTSStreaming:
    """Test TTS streaming and interruption support."""

    @pytest.mark.anyio
    async def test_kokoro_stream_synthesize(self, monkeypatch):
        """Kokoro stream_synthesize calls callback with audio chunks."""
        stt = KokoroTTS()

        chunks_received = []

        class MockKokoroVoice:
            def stream_synthesize(self, text):
                yield b"chunk1"
                yield b"chunk2"

        with patch("app.speech.tts.KokoroVoice", MockKokoroVoice):
            stt._voice = MockKokoroVoice()
            stt.stream_synthesize("test", lambda chunk: chunks_received.append(chunk))

        assert chunks_received == [b"chunk1", b"chunk2"]