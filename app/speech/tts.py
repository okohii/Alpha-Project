from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import wave
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings

try:
    from piper import PiperVoice
except Exception:  # pragma: no cover
    PiperVoice = None


class TextToSpeechError(RuntimeError):
    pass


class TextToSpeech(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> Path:
        raise NotImplementedError


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
            raise TextToSpeechError("Biblioteca Piper indisponível")

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
