from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KModel, KPipeline

from app.core.config import get_settings
from app.speech.delivery import DeliveryProcessor, DeliveryProfile

logger = logging.getLogger("app.speech.tts")


class TextToSpeechError(RuntimeError):
    pass


class TextToSpeech:
    async def synthesize(self, text: str, delivery: DeliveryProfile | None = None) -> Path:
        raise NotImplementedError


class KokoroTTS(TextToSpeech):
    """Kokoro-82M local com caminho otimizado para baixa latência."""

    def __init__(self) -> None:
        self.settings = get_settings()
        project_root = Path(__file__).resolve().parents[2]
        self.model_dir = project_root / "models" / "kokoro"
        self.config_path = self.model_dir / "config.json"
        self.model_path = self.model_dir / "kokoro-v1_0.pth"
        self.voice_path = self.model_dir / "voices" / "pf_dora.pt"
        self.voice = str(self.voice_path)
        self.sample_rate = 24000
        self._device = "cpu"
        self._validate_model_files()

        try:
            import torch

            requested = str(self.settings.tts_device).lower().strip()
            if requested == "cuda" or (requested == "auto" and torch.cuda.is_available()):
                self._device = "cuda"
        except Exception:
            self._device = "cpu"

        try:
            model = KModel(
                repo_id="hexgrad/Kokoro-82M",
                config=str(self.config_path),
                model=str(self.model_path),
            )
            if self._device == "cuda" and hasattr(model, "to"):
                model = model.to("cuda")
            self._pipeline = KPipeline(
                lang_code="p",
                repo_id="hexgrad/Kokoro-82M",
                model=model,
            )
        except Exception as exc:
            raise TextToSpeechError(f"Falha ao inicializar o Kokoro local: {exc}") from exc

        self._delivery = DeliveryProcessor()
        logger.info("[TTS] Kokoro pronto device=%s streaming=%s", self._device, self.settings.tts_streaming)

    def _validate_model_files(self) -> None:
        required_files = (self.config_path, self.model_path, self.voice_path)
        missing_files = [str(path) for path in required_files if not path.is_file()]
        if missing_files:
            raise TextToSpeechError(
                "Arquivos do Kokoro não encontrados:\n" + "\n".join(f" - {path}" for path in missing_files)
            )

    async def synthesize(self, text: str, delivery: DeliveryProfile | None = None) -> Path:
        if not text or not text.strip():
            raise TextToSpeechError("Não é possível sintetizar texto vazio.")
        try:
            return await asyncio.to_thread(self._synthesize, text.strip(), delivery)
        except TextToSpeechError:
            raise
        except Exception as exc:
            raise TextToSpeechError(f"Falha na síntese Kokoro: {exc}") from exc

    def _synthesize(self, text: str, delivery: DeliveryProfile | None = None) -> Path:
        profile = delivery or DeliveryProfile(speed=self.settings.tts_speed)
        prepared = self._delivery.prepare(text)
        segments = self._delivery.chunk(prepared, profile)
        if not segments:
            raise TextToSpeechError("Não é possível sintetizar texto vazio.")

        voice = profile.voice or self.voice
        temp_dir = Path(tempfile.mkdtemp(prefix="alpha-kokoro-"))
        output_path = temp_dir / "speech.wav"

        try:
            # Um único segmento para respostas curtas evita overhead de múltiplas
            # chamadas ao pipeline. Respostas longas continuam segmentadas.
            call_text: str | list[str] = segments[0] if len(segments) == 1 else segments
            generator = self._pipeline(call_text, voice=voice, speed=profile.speed)
            audio_chunks: list[np.ndarray] = []
            for _, _, audio in generator:
                if audio is None:
                    continue
                audio_array = np.asarray(audio)
                if audio_array.size:
                    audio_chunks.append(audio_array)
            if not audio_chunks:
                raise TextToSpeechError("Kokoro não gerou nenhum áudio.")

            full_audio = np.concatenate(audio_chunks)
            sf.write(str(output_path), full_audio, self.sample_rate)
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise TextToSpeechError("Kokoro não criou um arquivo de áudio válido.")
            return output_path
        except TextToSpeechError:
            raise
        except Exception as exc:
            raise TextToSpeechError(f"Erro durante a geração do áudio pelo Kokoro: {exc}") from exc
