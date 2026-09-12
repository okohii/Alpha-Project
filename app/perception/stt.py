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
    confidence: float = 1.0
    is_suspicious: bool = False


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: Path, initial_prompt: str | None = None) -> TranscriptionResult:
        raise NotImplementedError


def _determine_stt_device(settings_device: str) -> str:
    if settings_device == "cpu":
        return "cpu"
    if settings_device in ("auto", "cuda"):
        import subprocess

        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,no-header"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "cuda"
        except Exception:
            pass
    return "cpu"


def _compute_type_for_device(compute_type: str, device: str) -> str:
    if device == "cuda":
        return "float16" if compute_type == "auto" else compute_type
    return "int8" if compute_type == "auto" else compute_type


class FasterWhisperSTT(SpeechToText):
    """STT using Faster-Whisper with a latency-oriented decoding profile."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover
            raise SpeechToTextError("faster-whisper nao disponivel") from exc

        device = _determine_stt_device(self.settings.stt_device)
        compute_type = self.settings.stt_compute_type
        actual_compute_type = _compute_type_for_device(compute_type, device)

        self._model = WhisperModel(
            self.settings.stt_model_size,
            device=device,
            compute_type=actual_compute_type,
        )
        return self._model

    async def transcribe(
        self, audio_path: Path, initial_prompt: str | None = None
    ) -> TranscriptionResult:
        prompt = initial_prompt
        model = self._load_model()

        transcribe_kwargs: dict[str, Any] = {
            "language": self.settings.stt_language,
            "initial_prompt": prompt or None,
            "condition_on_previous_text": False,
            "beam_size": max(1, int(self.settings.stt_beam_size)),
            "best_of": max(1, int(self.settings.stt_best_of)),
            "temperature": float(self.settings.stt_temperature),
            "vad_filter": bool(self.settings.stt_vad_filter),
        }
        if transcribe_kwargs["vad_filter"]:
            transcribe_kwargs["vad_parameters"] = {
                "min_silence_duration_ms": max(100, int(self.settings.stt_vad_min_silence_ms)),
            }

        segments, info = model.transcribe(str(audio_path), **transcribe_kwargs)

        confidence = 1.0
        if hasattr(info, "language_probability") and info.language_probability is not None:
            confidence = float(info.language_probability)
        elif hasattr(info, "avg_logprob") and info.avg_logprob is not None:
            confidence = max(float(info.avg_logprob), 0.0)

        collected = []
        text_parts = []
        for segment in segments:
            collected.append(
                {"start": segment.start, "end": segment.end, "text": segment.text}
            )
            text_parts.append(segment.text)

        text = "".join(text_parts).strip()
        text_len = len(text)
        is_suspicious = (confidence < 0.3 and text_len < 3) or (text_len > 0 and confidence < 0.5)

        return TranscriptionResult(
            text=text,
            language=info.language or self.settings.stt_language,
            segments=collected,
            confidence=confidence,
            is_suspicious=is_suspicious,
        )
