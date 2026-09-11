from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

from app.core.config import get_settings


class TextToSpeechError(RuntimeError):
    """Erro relacionado à síntese de voz."""

    pass


class TextToSpeech:
    """Interface base para mecanismos de Text-to-Speech."""

    async def synthesize(self, text: str) -> Path:
        raise NotImplementedError


class KokoroTTS(TextToSpeech):
    """
    Implementação de TTS usando Kokoro-82M.

    O Kokoro é o mecanismo padrão de voz do ALPHA.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

        try:
            self._pipeline = KPipeline(lang_code="p")
        except Exception as exc:
            raise TextToSpeechError(
                f"Falha ao inicializar o Kokoro: {exc}"
            ) from exc

        # Voz padrão do Kokoro.
        #
        # Pode ser alterada posteriormente para uma configuração
        # como KOKORO_VOICE no .env.
        self.voice = "pf_dora"

        self.sample_rate = 24000

    async def synthesize(self, text: str) -> Path:
        """
        Gera um arquivo WAV usando o Kokoro.

        A geração é executada em uma thread para não bloquear
        o event loop principal do ALPHA.
        """

        if not text or not text.strip():
            raise TextToSpeechError(
                "Não é possível sintetizar texto vazio."
            )

        try:
            return await asyncio.to_thread(
                self._synthesize,
                text.strip(),
            )

        except TextToSpeechError:
            raise

        except Exception as exc:
            raise TextToSpeechError(
                f"Falha na síntese Kokoro: {exc}"
            ) from exc

    def _synthesize(self, text: str) -> Path:
        """
        Executa a síntese síncrona do Kokoro.
        """

        temp_dir = Path(
            tempfile.mkdtemp(
                prefix="alpha-kokoro-"
            )
        )

        output_path = temp_dir / "speech.wav"

        try:
            generator = self._pipeline(
                text,
                voice=self.voice,
            )

            audio_chunks: list[np.ndarray] = []

            for _, _, audio in generator:
                if audio is None:
                    continue

                audio_array = np.asarray(audio)

                if audio_array.size == 0:
                    continue

                audio_chunks.append(audio_array)

            if not audio_chunks:
                raise TextToSpeechError(
                    "Kokoro não gerou nenhum áudio."
                )

            full_audio = np.concatenate(
                audio_chunks
            )

            sf.write(
                str(output_path),
                full_audio,
                self.sample_rate,
            )

            if not output_path.exists():
                raise TextToSpeechError(
                    "Kokoro não criou o arquivo de áudio."
                )

            if output_path.stat().st_size == 0:
                raise TextToSpeechError(
                    "Kokoro criou um arquivo de áudio vazio."
                )

            return output_path

        except TextToSpeechError:
            raise

        except Exception as exc:
            raise TextToSpeechError(
                f"Erro durante a geração do áudio pelo Kokoro: {exc}"
            ) from exc