from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

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
    """Determine the actual STT device based on settings and available hardware.

    Args:
        settings_device: Device string from settings ("auto", "cuda", "cpu").

    Returns:
        "cuda" if NVIDIA GPU is available and requested,
        "cpu" otherwise.
    """
    if settings_device == "cpu":
        return "cpu"
    if settings_device in ("auto", "cuda"):
        import subprocess

        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,no-headers"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "cuda"
        except Exception:
            pass
    return "cpu"


def _compute_type_for_device(compute_type: str, device: str) -> str:
    """Resolve the compute type for the given device.

    Args:
        compute_type: The requested compute type ("auto", "int8", "float16", etc.).
        device: The target device ("cuda" or "cpu").

    Returns:
        The effective compute type suitable for the device.
    """
    if device == "cuda":
        return "float16" if compute_type == "auto" else compute_type
    return "int8" if compute_type == "auto" else compute_type


class FasterWhisperSTT(SpeechToText):
    """STT using Faster-Whisper with device selection and improved options."""

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
        # Only use initial_prompt if explicitly provided by the caller.
        # A generic default prompt biases short commands, so we ignore
        # the settings default unless the caller supplies one.
        prompt = initial_prompt

        model = self._load_model()

        # Use condition_on_previous_text=False for short commands to avoid
        # carry-over context from previous transcriptions.
        segments, info = model.transcribe(
            str(audio_path),
            language=self.settings.stt_language,
            initial_prompt=prompt or None,
            condition_on_previous_text=False,
        )

        # Extract confidence from info if available
        confidence = 1.0
        if hasattr(info, "language_probability") and info.language_probability is not None:
            confidence = float(info.language_probability)
        elif hasattr(info, "avg_logprob") and info.avg_logprob is not None:
            confidence = max(float(info.avg_logprob), 0.0)

        # Detect suspicious transcriptions (very low confidence, very short text,
        # or language mismatch) to flag potentially erroneous results.
        is_suspicious = False
        text = (info.language or self.settings.stt_language) or "pt"
        text_len = len(info.text) if hasattr(info, "text") else 0

        if confidence < 0.3 and text_len < 3:
            is_suspicious = True
        elif text_len > 0 and confidence < 0.5:
            is_suspicious = True

        collected = []
        text_parts = []
        for segment in segments:
            collected.append(
                {"start": segment.start, "end": segment.end, "text": segment.text}
            )
            text_parts.append(segment.text)

        return TranscriptionResult(
            text="".join(text_parts).strip(),
            language=info.language or self.settings.stt_language,
            segments=collected,
            confidence=confidence,
            is_suspicious=is_suspicious,
        )
