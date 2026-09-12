from __future__ import annotations

import asyncio
import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("app.perception.stt")
_HAS_ALNUM_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]")
_ALNUM_RE = re.compile(r"[^A-Za-zÀ-ÿ0-9]")


class SpeechToTextError(RuntimeError):
    pass


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str
    segments: list[dict[str, Any]]
    confidence: float = 1.0
    is_suspicious: bool = False
    is_usable: bool = True


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: Path, initial_prompt: str | None = None) -> TranscriptionResult:
        raise NotImplementedError


def _cuda_available() -> bool:
    """Check the actual CTranslate2 CUDA backend used by faster-whisper."""
    try:
        import ctranslate2
        count = int(ctranslate2.get_cuda_device_count())
        if count <= 0:
            return False
        supported = ctranslate2.get_supported_compute_types("cuda")
        return bool(supported)
    except Exception as exc:
        logger.warning("[stt] cuda_backend_unavailable reason=%s", exc)
        return False


def _determine_stt_device(settings_device: str) -> str:
    requested = str(settings_device or "auto").lower().strip()
    if requested == "cpu":
        return "cpu"
    available = _cuda_available()
    if requested == "cuda":
        if not available:
            raise SpeechToTextError(
                "STT configurado para CUDA, mas o backend CUDA do CTranslate2 não está disponível. "
                "Instale uma versão CUDA de ctranslate2/faster-whisper compatível com sua GPU."
            )
        return "cuda"
    if requested == "auto":
        return "cuda" if available else "cpu"
    raise SpeechToTextError(f"Dispositivo STT inválido: {settings_device!r}")


def _compute_type_for_device(compute_type: str, device: str) -> str:
    requested = str(compute_type or "auto").lower().strip()
    if device == "cuda":
        if requested == "auto":
            return "float16"
        return requested
    if requested == "auto":
        return "int8"
    return requested


def _is_usable_text(text: str) -> bool:
    cleaned = (text or "").strip()
    if not _HAS_ALNUM_RE.search(cleaned):
        return False
    return len(_ALNUM_RE.sub("", cleaned)) >= 2


def _decoded_confidence(segments: list[dict[str, Any]], language_probability: float) -> float:
    if not segments:
        return 0.0
    scores: list[float] = []
    for segment in segments:
        logprob = segment.get("avg_logprob")
        no_speech = segment.get("no_speech_prob")
        if isinstance(logprob, (int, float)):
            log_score = max(0.0, min(1.0, math.exp(float(logprob))))
        else:
            log_score = 0.5
        speech_score = 1.0 - max(0.0, min(1.0, float(no_speech))) if isinstance(no_speech, (int, float)) else 0.5
        scores.append((log_score + speech_score) / 2.0)
    decoded = sum(scores) / len(scores)
    return max(0.0, min(1.0, decoded * max(0.0, min(1.0, float(language_probability)))))


class FasterWhisperSTT(SpeechToText):
    """STT using Faster-Whisper; all model/decode work stays off the event loop."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None
        self._wake_model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise SpeechToTextError("faster-whisper nao disponivel") from exc
        device = _determine_stt_device(self.settings.stt_device)
        compute_type = _compute_type_for_device(self.settings.stt_compute_type, device)
        logger.info("[stt] loading model=%s device=%s compute_type=%s language=%s", self.settings.stt_model_size, device, compute_type, self.settings.stt_language)
        self._model = WhisperModel(self.settings.stt_model_size, device=device, compute_type=compute_type)
        logger.info("[stt] model_ready device=%s compute_type=%s", device, compute_type)
        return self._model

    def _load_wake_model(self):
        if self._wake_model is not None:
            return self._wake_model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise SpeechToTextError("faster-whisper nao disponivel") from exc
        device = _determine_stt_device(self.settings.stt_wake_device)
        compute_type = _compute_type_for_device(self.settings.stt_compute_type, device)
        size = self.settings.stt_wake_model_size or "tiny"
        logger.info("[stt] loading wake_model=%s device=%s compute_type=%s", size, device, compute_type)
        self._wake_model = WhisperModel(size, device=device, compute_type=compute_type)
        logger.info("[stt] wake_model_ready device=%s compute_type=%s", device, compute_type)
        return self._wake_model

    async def warmup(self) -> None:
        await asyncio.to_thread(self._load_model)

    async def warmup_wake(self) -> None:
        await asyncio.to_thread(self._load_wake_model)

    async def transcribe_wake(self, audio_path: Path) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, "", True)

    async def transcribe(self, audio_path: Path, initial_prompt: str | None = None) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, initial_prompt, False)

    def _transcribe_sync(self, audio_path: Path, initial_prompt: str | None, wake_only: bool) -> TranscriptionResult:
        model = self._load_wake_model() if wake_only else self._load_model()
        prompt = initial_prompt
        try:
            import wave
            with wave.open(str(audio_path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate() if wav.getframerate() else 0.0
                logger.info("[stt] transcribe_start mode=%s path=%s duration=%.2fs rate=%d frames=%d", "wake" if wake_only else "full", audio_path, duration, wav.getframerate(), wav.getnframes())
        except Exception:
            duration = 0.0

        # O wake model não deve limitar uma frase real a poucos tokens.
        # Ele precisa continuar leve, mas deve conseguir atravessar toda a
        # gravação para encontrar "Alpha/Alfa" e preservar o comando falado.
        if wake_only:
            max_new_tokens = max(16, min(64, int(math.ceil(max(duration, 1.0) * 8))))
            decode_beam_size = 1
            decode_best_of = 1
        else:
            max_new_tokens = None
            decode_beam_size = max(1, int(self.settings.stt_beam_size))
            decode_best_of = max(1, int(self.settings.stt_best_of))

        kwargs: dict[str, Any] = {
            "language": self.settings.stt_language,
            "initial_prompt": prompt or None,
            "condition_on_previous_text": False,
            "beam_size": decode_beam_size,
            "best_of": decode_best_of,
            "temperature": 0.0,
            "vad_filter": bool(self.settings.stt_vad_filter),
            "without_timestamps": True,
        }
        if self.settings.stt_vad_filter:
            kwargs["vad_parameters"] = {"min_silence_duration_ms": max(100, int(self.settings.stt_vad_min_silence_ms))}
        if max_new_tokens is not None:
            kwargs["max_new_tokens"] = max_new_tokens

        logger.debug("[stt] decode_kwargs=%s", {k: v for k, v in kwargs.items() if k != "initial_prompt"})
        segments, info = model.transcribe(str(audio_path), **kwargs)
        collected: list[dict[str, Any]] = []
        text_parts: list[str] = []
        for segment in segments:
            collected.append({"start": segment.start, "end": segment.end, "text": segment.text, "avg_logprob": getattr(segment, "avg_logprob", None), "no_speech_prob": getattr(segment, "no_speech_prob", None)})
            text_parts.append(segment.text)
        text = "".join(text_parts).strip()
        usable = _is_usable_text(text)
        text_len = len(_ALNUM_RE.sub("", text))
        language_probability = float(getattr(info, "language_probability", 1.0) or 1.0)
        confidence = _decoded_confidence(collected, language_probability)
        threshold = 0.25 if wake_only else 0.35
        is_suspicious = (not usable) or (confidence < threshold) or (text_len > 0 and confidence < 0.55)
        logger.info("[stt] transcribe_end mode=%s duration=%.2fs text=%r confidence=%.3f language_probability=%.3f usable=%s suspicious=%s segments=%d", "wake" if wake_only else "full", duration, text, confidence, language_probability, usable, is_suspicious, len(collected))
        return TranscriptionResult(text=text, language=info.language or self.settings.stt_language, segments=collected, confidence=confidence, is_suspicious=is_suspicious, is_usable=usable)
