from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Callable, Optional

from kokoro import KPipeline
import soundfile as sf

from app.core.config import get_settings

try:
    from kokoro_ml import KokoroVoice
except Exception:  # pragma: no cover
    KokoroVoice = None


class TextToSpeechError(RuntimeError):
    pass


class TextToSpeech(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> Path:
        raise NotImplementedError


class KokoroTTS(TextToSpeech):
    def __init__(self) -> None:
        self.settings = get_settings()
        self._voice: Optional[object] = None
        self._pipeline = KPipeline(lang_code='a')

    async def synthesize(self, text: str) -> Path:
        """Synthesize speech from text using Kokoro.

        Returns:
            Path to a WAV file containing the synthesized speech.
        """
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix="alpha-tts-"))
            output_path = temp_dir / "speech.wav"

            generator = self._pipeline(text, voice='af_heart')
            audio_chunks = []
            for i, (gs, ps, audio) in enumerate(generator):
                audio_chunks.append(audio)

            if not audio_chunks:
                raise TextToSpeechError("Nenhum audio gerado")

            # Concatenate all audio chunks
            import numpy as np
            full_audio = np.concatenate(audio_chunks)

            # Write to WAV file
            sf.write(str(output_path), full_audio, 24000)

        except Exception as exc:
            raise TextToSpeechError(f"Falha na sintetizacao Kokoro: {exc}") from exc

        if not output_path.exists():
            raise TextToSpeechError("Kokoro nao gerou audio")
        return output_path

    def stream_synthesize(self, text: str, on_chunk: Callable[[bytes], None]) -> None:
        """Stream synthesis chunks as they are generated.

        Args:
            text: The text to synthesize.
            on_chunk: Callback receiving audio bytes chunks.
        """
        if self._voice is None and KokoroVoice is not None:
            model_path = (
                self.settings.tts_voice
                or os.environ.get("KOKORO_MODEL")
                or "hexgrad/Kokoro-82M"
            )
            try:
                self._voice = KokoroVoice(model_path)
            except Exception:
                return

        if self._voice is not None:
            try:
                chunks = self._voice.stream_synthesize(text)
                for chunk in chunks:
                    on_chunk(chunk)
            except Exception:
                pass


class PiperTTS(TextToSpeech):
    def __init__(self) -> None:
        self.settings = get_settings()
        self._voice = None
        self.piper_executable = (
            os.environ.get("PIPER_BIN")
            or os.environ.get("PIPER_EXECUTABLE")
            or shutil.which("piper")
            or shutil.which("piper.exe")
            or r"C:\piper\piper.exe"
        )
        self.model_path = (
            self.settings.tts_voice
            or os.environ.get("PIPER_MODEL")
            or r"C:\piper\models\pt_BR\cadu\medium\pt_BR-cadu-medium.onnx"
        )

    async def synthesize(self, text: str) -> Path:
        if not self.model_path:
            raise TextToSpeechError("Modelo de voz do Piper não configurado")

        model_path = Path(self.model_path).expanduser()
        if not model_path.exists():
            raise TextToSpeechError(f"Modelo de voz do Piper não encontrado: {model_path}")

        if PiperVoice is not None:
            try:
                return await asyncio.to_thread(self._synthesize_with_library, text, model_path)
            except TextToSpeechError:
                raise
            except Exception as exc:  # pragma: no cover
                if not self.piper_executable:
                    raise TextToSpeechError(f"Falha no Piper: {exc}") from exc

        if not self.piper_executable:
            raise TextToSpeechError("Piper não instalado ou não encontrado no PATH")

        return await self._synthesize_with_cli(text, model_path)

    def _synthesize_with_library(self, text: str, model_path: Path) -> Path:
        if PiperVoice is None:
            raise TextToSpeechError("Biblioteca Piper indisponivel")

        if self._voice is None:
            self._voice = PiperVoice.load(model_path)

        temp_dir = Path(tempfile.mkdtemp(prefix="alpha-tts-"))
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / "speech.wav"
        try:
            with wave.open(str(output_path), "wb") as wav_file:
                self._voice.synthesize_wav(text, wav_file)
        except Exception as exc:  # pragma: no cover
            raise TextToSpeechError(f"Falha no Piper: {exc}") from exc

        if not output_path.exists():
            raise TextToSpeechError("Piper não gerou áudio")
        return output_path

    async def _synthesize_with_cli(self, text: str, model_path: Path) -> Path:
        command = [
            self.piper_executable,
            "--model",
            str(model_path),
            "--output_file",
            "/tmp/alpha-tts.wav",
        ]

        temp_dir = Path(tempfile.mkdtemp(prefix="alpha-tts-"))
        output_path = temp_dir / "speech.wav"
        command[-1] = str(output_path)

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=f"{text}\n".encode()),
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise TextToSpeechError("Piper não instalado") from exc
        except TimeoutError as exc:
            if "process" in locals():
                process.kill()
                await process.wait()
            raise TextToSpeechError("Piper demorou muito para responder") from exc
        except Exception as exc:  # pragma: no cover
            raise TextToSpeechError(f"Falha no Piper: {exc}") from exc

        if process.returncode != 0:
            output = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
            message = output or "código de saída " + str(process.returncode)
            raise TextToSpeechError(f"Falha no Piper: {message}")

        if not output_path.exists():
            raise TextToSpeechError("Piper não gerou áudio")
        return output_path