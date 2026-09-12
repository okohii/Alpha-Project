from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from app.speech.tts import KokoroTTS, TextToSpeechError

CHUNK = np.zeros(2400, dtype=np.float32)


class FakePipeline:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, text, voice=None, speed=None):
        for index in range(3):
            yield (index, "", CHUNK)
        return None


class DummyModel:
    def __init__(self, *args, **kwargs):
        pass


def _patch_kokoro(monkeypatch, pipeline_cls):
    """Neutraliza KModel + KPipeline + validação de arquivos locais."""
    monkeypatch.setattr("app.speech.tts.KModel", DummyModel)
    monkeypatch.setattr("app.speech.tts.KPipeline", pipeline_cls)
    monkeypatch.setattr(KokoroTTS, "_validate_model_files", lambda self: None)


class TestKokoroTTS:
    """Test Kokoro TTS integration."""

    @pytest.mark.anyio
    async def test_kokoro_synthesize_raises_when_pipeline_missing(self, monkeypatch):
        """Constructor raises TextToSpeechError if kokoro (KPipeline) is unavailable."""
        with patch("app.speech.tts.KPipeline", side_effect=ImportError("sem kokoro")):
            monkeypatch.setattr(KokoroTTS, "_validate_model_files", lambda self: None)
            with pytest.raises(TextToSpeechError, match="Falha ao inicializar o Kokoro local"):
                KokoroTTS()

    @pytest.mark.anyio
    async def test_kokoro_synthesize_success(self, monkeypatch):
        """Synthesize successfully creates a WAV file from pipeline output."""
        _patch_kokoro(monkeypatch, FakePipeline)
        stt = KokoroTTS()
        result = await stt.synthesize("teste")

        assert Path(result).exists()
        assert str(result).endswith(".wav")
        assert Path(result).stat().st_size > 0
        import wave

        with wave.open(str(result), "rb") as wav_file:
            assert wav_file.getframerate() == stt.sample_rate

    @pytest.mark.anyio
    async def test_kokoro_synthesize_concatenates_chunks(self, monkeypatch):
        """Multi-chunk audio from the pipeline is concatenated into one WAV."""
        class TwoChunkPipeline(FakePipeline):
            def __call__(self, text, voice=None, speed=None):
                for index in range(2):
                    yield (index, "", np.ones(1200, dtype=np.float32))
                return None

        _patch_kokoro(monkeypatch, TwoChunkPipeline)
        stt = KokoroTTS()
        result = await stt.synthesize("chunks")

        import soundfile as sf

        data, _ = sf.read(str(result), dtype="float32")
        assert len(data) == 2400

    @pytest.mark.anyio
    async def test_synthesize_honors_delivery_profile(self, monkeypatch):
        """DeliveryProfile controls speed, segmentation and keeps pf_dora."""
        captured = {}

        class CapturePipeline(FakePipeline):
            def __call__(self, text, voice=None, speed=None):
                captured["text"] = text
                captured["voice"] = voice
                captured["speed"] = speed
                for index in range(2):
                    yield (index, "", CHUNK)
                return None

        _patch_kokoro(monkeypatch, CapturePipeline)
        from app.speech.delivery import DeliveryProfile

        profile = DeliveryProfile(
            speed=1.06,
            chunk_strategy="standard",
        )
        stt = KokoroTTS()
        result = await stt.synthesize(
            "Boa! Encontrei a macro que você pediu. Ela está agendada para amanhã.",
            delivery=profile,
        )

        assert Path(result).exists()
        assert list(captured["text"]) == [
            "Boa! Encontrei a macro que você pediu.",
            "Ela está agendada para amanhã.",
        ]
        assert captured["speed"] == 1.06
        assert captured["voice"] is not None
        assert "pf_dora" in Path(captured["voice"]).name
        assert str(captured["voice"]).endswith(".pt")

    @pytest.mark.anyio
    async def test_synthesize_empty_text_raises(self, monkeypatch):
        _patch_kokoro(monkeypatch, FakePipeline)
        stt = KokoroTTS()
        with pytest.raises(TextToSpeechError):
            await stt.synthesize("   ")

    @pytest.mark.anyio
    async def test_synthesize_no_audio_raises(self, monkeypatch):
        """Pipeline producing no chunks raises TextToSpeechError."""
        class EmptyPipeline(FakePipeline):
            def __call__(self, text, voice=None, speed=None):
                return iter([])

        _patch_kokoro(monkeypatch, EmptyPipeline)
        stt = KokoroTTS()
        with pytest.raises(TextToSpeechError, match="não gerou nenhum áudio"):
            await stt.synthesize("vazio")

    @pytest.mark.anyio
    async def test_synthesize_missing_model_files_raise(self, monkeypatch):
        """Missing local model files fail fast at construction time."""
        monkeypatch.setattr(KokoroTTS, "_validate_model_files", lambda self: (_ for _ in ()).throw(
            TextToSpeechError("Arquivos do Kokoro não encontrados:\n - x")
        ))
        with pytest.raises(TextToSpeechError, match="Arquivos do Kokoro"):
            KokoroTTS()