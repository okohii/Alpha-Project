from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class SpeechToTextError(RuntimeError):
    pass


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str
    segments: list[dict[str, Any]]


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        raise NotImplementedError


class FasterWhisperSTT(SpeechToText):
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover
            raise SpeechToTextError("faster-whisper não está disponível") from exc
        device = "cpu" if self.settings.stt_device == "auto" else self.settings.stt_device
        compute_type = (
            "int8" if self.settings.stt_compute_type == "auto" else self.settings.stt_compute_type
        )
        self._model = WhisperModel(
            self.settings.stt_model_size, device=device, compute_type=compute_type
        )
        return self._model

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        model = self._load_model()
        initial_prompt = getattr(self.settings, "stt_initial_prompt", "").strip()
        if initial_prompt:
            segments, info = model.transcribe(
                str(audio_path),
                language=self.settings.stt_language,
                initial_prompt=initial_prompt,
            )
        else:
            segments, info = model.transcribe(str(audio_path), language=self.settings.stt_language)
        collected = []
        text_parts = []
        for segment in segments:
            collected.append({"start": segment.start, "end": segment.end, "text": segment.text})
            text_parts.append(segment.text)
        return TranscriptionResult(
            text="".join(text_parts).strip(),
            language=info.language or self.settings.stt_language,
            segments=collected,
        )
