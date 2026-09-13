from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

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
        self._torch = None
        self._validate_model_files()

        try:
            import torch
            self._torch = torch
            requested = str(self.settings.tts_device).lower().strip()
            cuda_available = bool(torch.cuda.is_available())
            if requested == "cuda" and not cuda_available:
                raise TextToSpeechError(
                    "TTS configurado para CUDA, mas torch.cuda.is_available() retornou False. "
                    "Instale uma build CUDA do PyTorch compatível com sua RTX 3050."
                )
            if requested not in {"auto", "cuda", "cpu"}:
                raise TextToSpeechError(f"Dispositivo TTS inválido: {self.settings.tts_device!r}")
            if requested == "cuda" or (requested == "auto" and cuda_available):
                self._device = "cuda"
                logger.info("[TTS] CUDA disponível gpu=%s", torch.cuda.get_device_name(0))
            if hasattr(torch, "set_float32_matmul_precision"):
                torch.set_float32_matmul_precision("high")
        except TextToSpeechError:
            raise
        except Exception as exc:
            raise TextToSpeechError(f"Falha ao detectar dispositivo do Kokoro: {exc}") from exc

        try:
            model = KModel(
                repo_id="hexgrad/Kokoro-82M",
                config=str(self.config_path),
                model=str(self.model_path),
            )
            if self._device == "cuda" and hasattr(model, "to"):
                model = model.to("cuda")
            if hasattr(model, "eval"):
                model = model.eval()
            self._model = model
            self._pipeline = KPipeline(
                lang_code="p",
                repo_id="hexgrad/Kokoro-82M",
                model=model,
            )
        except Exception as exc:
            raise TextToSpeechError(f"Falha ao inicializar o Kokoro local: {exc}") from exc

        self._delivery = DeliveryProcessor()
        # Kokoro não é seguro para inferência concorrente entre sessões
        # (avatar + overlay + /voice): trava única por processo (Fase 4.5).
        self._engine_lock = threading.Lock()
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
            with self._torch.inference_mode() if self._torch is not None else _nullcontext():
                with self._engine_lock:
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
        queue: asyncio.Queue[Path | BaseException | None] = asyncio.Queue(maxsize=8)

        def _enqueue(item: Any, attempts: int = 50) -> bool:
            """Insere sem deadlock: se a fila estiver cheia, aguarda curto e
            desiste depois de ~2.5s (consumidor cancelado não trava a thread)."""
            for _ in range(attempts):
                try:
                    queue.put_nowait(item)
                    return True
                except asyncio.QueueFull:
                    time.sleep(0.05)
            logger.warning("[tts] stream queue full: descartando item de áudio")
            return False

        def worker() -> None:
            temp_dir = Path(tempfile.mkdtemp(prefix="alpha-kokoro-stream-"))
            try:
                with self._torch.inference_mode() if self._torch is not None else _nullcontext():
                    with self._engine_lock:
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
                            if not _enqueue(path):
                                return
            except BaseException as exc:
                _enqueue(exc)
            finally:
                _enqueue(None)

        thread = threading.Thread(target=worker, name="alpha-kokoro-stream", daemon=True)
        thread.start()
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
