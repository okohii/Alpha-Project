from __future__ import annotations

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


def _determine_stt_device(settings_device: str) -> str:
    if settings_device == "cpu": return "cpu"
    if settings_device in ("auto", "cuda"):
        import subprocess
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,no-header"], capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip(): return "cuda"
        except Exception: pass
    return "cpu"


def _compute_type_for_device(compute_type: str, device: str) -> str:
    if device == "cuda": return "float16" if compute_type == "auto" else compute_type
    return "int8" if compute_type == "auto" else compute_type


def _is_usable_text(text: str) -> bool:
    cleaned = (text or "").strip()
    if not _HAS_ALNUM_RE.search(cleaned): return False
    return len(_ALNUM_RE.sub("", cleaned)) >= 2


def _decoded_confidence(segments: list[dict[str, Any]], language_probability: float) -> float:
    if not segments: return 0.0
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
    """STT using Faster-Whisper; audio segmentation is owned by ALPHA's capture VAD."""
    def __init__(self) -> None:
        self.settings = get_settings(); self._model = None

    def _load_model(self):
        if self._model is not None: return self._model
        try: from faster_whisper import WhisperModel
        except Exception as exc: raise SpeechToTextError("faster-whisper nao disponivel") from exc
        device = _determine_stt_device(self.settings.stt_device); compute_type = _compute_type_for_device(self.settings.stt_compute_type, device)
        logger.info("[stt] loading model=%s device=%s compute_type=%s language=%s",self.settings.stt_model_size,device,compute_type,self.settings.stt_language)
        self._model = WhisperModel(self.settings.stt_model_size, device=device, compute_type=compute_type)
        logger.info("[stt] model_ready")
        return self._model

    async def warmup(self) -> None:
        """Load the STT model before the first user command, outside the hot path."""
        await __import__("asyncio").to_thread(self._load_model)

    async def transcribe(self, audio_path: Path, initial_prompt: str | None = None) -> TranscriptionResult:
        prompt = initial_prompt; model = self._load_model()
        try:
            with __import__("wave").open(str(audio_path), "rb") as wav:
                duration=wav.getnframes()/wav.getframerate() if wav.getframerate() else 0.0
                logger.info("[stt] transcribe_start path=%s duration=%.2fs rate=%d frames=%d",audio_path,duration,wav.getframerate(),wav.getnframes())
        except Exception: duration=0.0
        transcribe_kwargs: dict[str, Any] = {"language":self.settings.stt_language,"initial_prompt":prompt or None,"condition_on_previous_text":False,"beam_size":max(1,int(self.settings.stt_beam_size)),"best_of":max(1,int(self.settings.stt_best_of)),"temperature":float(self.settings.stt_temperature),"vad_filter":False}
        logger.debug("[stt] decode_kwargs=%s",{k:v for k,v in transcribe_kwargs.items() if k!="initial_prompt"})
        segments, info = model.transcribe(str(audio_path), **transcribe_kwargs)
        collected=[]; text_parts=[]
        for segment in segments:
            collected.append({"start":segment.start,"end":segment.end,"text":segment.text,"avg_logprob":getattr(segment,"avg_logprob",None),"no_speech_prob":getattr(segment,"no_speech_prob",None)}); text_parts.append(segment.text)
        text="".join(text_parts).strip(); usable=_is_usable_text(text); text_len=len(_ALNUM_RE.sub("",text)); language_probability=float(getattr(info,"language_probability",1.0) or 1.0)
        confidence=_decoded_confidence(collected,language_probability)
        is_suspicious=(not usable) or (confidence<0.35) or (text_len>0 and confidence<0.55)
        logger.info("[stt] transcribe_end duration=%.2fs text=%r confidence=%.3f language_probability=%.3f usable=%s suspicious=%s segments=%d",duration,text,confidence,language_probability,usable,is_suspicious,len(collected))
        return TranscriptionResult(text=text,language=info.language or self.settings.stt_language,segments=collected,confidence=confidence,is_suspicious=is_suspicious,is_usable=usable)
