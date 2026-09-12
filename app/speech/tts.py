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
    """Erro relacionado à síntese de voz."""

    pass


class TextToSpeech:
    """Interface base para mecanismos de Text-to-Speech."""

    async def synthesize(self, text: str, delivery: DeliveryProfile | None = None) -> Path:
        raise NotImplementedError


class KokoroTTS(TextToSpeech):
    """
    Implementação de TTS usando Kokoro-82M local.

    O modelo e a voz são carregados a partir dos arquivos
    presentes no diretório models/kokoro.

    O runtime não depende de download do Hugging Face.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

        # Diretório dos modelos Kokoro.
        #
        # Estrutura esperada:
        #
        # models/
        # └── kokoro/
        #     ├── config.json
        #     ├── kokoro-v1_0.pth
        #     └── voices/
        #         └── pf_dora.pt
        #
        project_root = Path(__file__).resolve().parents[2]

        self.model_dir = project_root / "models" / "kokoro"
        self.config_path = self.model_dir / "config.json"
        self.model_path = self.model_dir / "kokoro-v1_0.pth"
        self.voice_path = self.model_dir / "voices" / "pf_dora.pt"

        self.voice = str(self.voice_path)
        self.sample_rate = 24000

        self._validate_model_files()

        try:
            # Carrega os pesos diretamente do disco.
            #
            # Não usamos KPipeline(lang_code="p"), pois essa
            # forma permite que o Kokoro tente resolver o modelo
            # através do Hugging Face.
            model = KModel(
                repo_id="hexgrad/Kokoro-82M",
                config=str(self.config_path),
                model=str(self.model_path),
            )

            # Pipeline usando o KModel já carregado localmente.
            self._pipeline = KPipeline(
                lang_code="p",
                repo_id="hexgrad/Kokoro-82M",
                model=model,
            )

        except Exception as exc:
            raise TextToSpeechError(
                f"Falha ao inicializar o Kokoro local: {exc}"
            ) from exc

    def _validate_model_files(self) -> None:
        """Verifica se os arquivos necessários existem."""

        required_files = (
            self.config_path,
            self.model_path,
            self.voice_path,
        )

        missing_files = [
            str(path)
            for path in required_files
            if not path.is_file()
        ]

        if missing_files:
            raise TextToSpeechError(
                "Arquivos do Kokoro não encontrados:\n"
                + "\n".join(f" - {path}" for path in missing_files)
            )

    async def synthesize(self, text: str, delivery: DeliveryProfile | None = None) -> Path:
        """
        Gera um arquivo WAV usando o Kokoro.

        ``delivery`` (opcional) controla velocidade, voz e segmentação usando
        apenas parâmetros reais do Kokoro. ``None`` → comportamento atual.

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
                delivery,
            )

        except TextToSpeechError:
            raise

        except Exception as exc:
            raise TextToSpeechError(
                f"Falha na síntese Kokoro: {exc}"
            ) from exc

    def _synthesize(self, text: str, delivery: DeliveryProfile | None = None) -> Path:
        """Executa a síntese síncrona do Kokoro."""

        profile = delivery or DeliveryProfile()
        segments = DeliveryProcessor().chunk(text, profile)
        if not segments:
            raise TextToSpeechError(
                "Não é possível sintetizar texto vazio."
            )

        voice = profile.voice or self.voice

        temp_dir = Path(
            tempfile.mkdtemp(
                prefix="alpha-kokoro-"
            )
        )

        output_path = temp_dir / "speech.wav"

        try:
            # A segmentação por sentença (``segments``) controla as pausas
            # naturais entre segmentos; ``speed`` é um parâmetro real do
            # Kokoro. Nenhum tag/instrução teatral chega ao pipeline.
            call_text: str | list[str] = segments[0] if len(segments) == 1 else segments
            generator = self._pipeline(
                call_text,
                voice=voice,
                speed=profile.speed,
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

            logger.info(
                "[TTS] delivery speed=%.2f voice=%s strategy=%s segments=%d",
                profile.speed,
                Path(voice).name if voice else "default",
                profile.chunk_strategy.value,
                len(segments),
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
