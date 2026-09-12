from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
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

    async def synthesize_stream(self, text: str, delivery: DeliveryProfile | None = None):
        raise NotImplementedError


class KokoroTTS(TextToSpeech):
    """Kokoro-82M local com síntese inteira e incremental por segmento."""

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

    def _prepare(self, text: str, delivery: DeliveryProfile | None) -> tuple[DeliveryProfile, list[str], str]:
        if not text or not text.strip():
            raise TextToSpeechError("Não é possível sintetizar texto vazio.")
        profile = delivery or DeliveryProfile(speed=self.settings.tts_speed)
        prepared = self._delivery.prepare(text.strip())
        segments = self._delivery.chunk(prepared, profile)
        if not segments:
            raise TextToSpeechError("Não é possível sintetizar texto vazio.")
        return profile, segments, prepared

    async def synthesize(self, text: str, delivery: DeliveryProfile | None = None) -> Path:
        try:
            return await asyncio.to_thread(self._synthesize, text, delivery)
        except TextToSpeechError:
            raise
        except Exception as exc:
            raise TextToSpeechError(f"Falha na síntese Kokoro: {exc}") from exc

    def _synthesize(self, text: str, delivery: DeliveryProfile | None = None) -> Path:
        profile, segments, _ = self._prepare(text, delivery)
        voice = profile.voice or self.voice
        temp_dir = Path(tempfile.mkdtemp(prefix="alpha-kokoro-"))
        output_path = temp_dir / "speech.wav"
        try:
            generator = self._pipeline(segments[0] if len(segments) == 1 else segments, voice=voice, speed=profile.speed)
            audio_chunks: list[np.ndarray] = []
            for _, _, audio in generator:
                if audio is not None:
                    audio_array = np.asarray(audio)
                    if audio_array.size:
                        audio_chunks.append(audio_array)
            if not audio_chunks:
                raise TextToSpeechError("Kokoro não gerou nenhum áudio.")
            sf.write(str(output_path), np.concatenate(audio_chunks), self.sample_rate)
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise TextToSpeechError("Kokoro não criou um arquivo de áudio válido.")
            return output_path
        except TextToSpeechError:
            raise
        except Exception as exc:
            raise TextToSpeechError(f"Erro durante a geração do áudio pelo Kokoro: {exc}") from exc

    async def synthesize_stream(self, text: str, delivery: DeliveryProfile | None = None):
        """Gera e entrega cada segmento sem esperar a resposta inteira."""
        profile, segments, _ = self._prepare(text, delivery)
        voice = profile.voice or self.voice
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Path | BaseException | None] = asyncio.Queue(maxsize=2)

        def worker() -> None:
            temp_dir = Path(tempfile.mkdtemp(prefix="alpha-kokoro-stream-"))
            try:
                for index, segment in enumerate(segments):
                    generator = self._pipeline(segment, voice=voice, speed=profile.speed)
                    audio_chunks: list[np.ndarray] = []
                    for _, _, audio in generator:
                        if audio is None:
                            continue
                        audio_array = np.asarray(audio)
                        if audio_array.size:
                            audio_chunks.append(audio_array)
                    if not audio_chunks:
                        raise TextToSpeechError(f"Kokoro não gerou áudio para o segmento {index + 1}.")
                    path = temp_dir / f"chunk_{index:03d}.wav"
                    sf.write(str(path), np.concatenate(audio_chunks), self.sample_rate)
                    asyncio.run_coroutine_threadsafe(queue.put(path), loop).result()
            except BaseException as exc:
                asyncio.run_coroutine_threadsafe(queue.put(exc), loop).result()
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

        thread = threading.Thread(target=worker, name="alpha-kokoro-stream", daemon=True)
        thread.start()
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
