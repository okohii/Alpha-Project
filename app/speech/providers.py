"""Provedores de voz com cache por PROCESSO.

STT/TTS são carregados UMA vez por processo (Parte 28/29). Recriar pipeline por
request/sessão não recarrega mais os modelos: as instâncias compartilhadas são
pré-aquecidas no startup e reutilizadas; o trabalho pesado roda em threads.
"""
from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_CACHE: dict[str, Any] = {}


def get_shared_stt():
    """Retorna o FasterWhisperSTT do processo (singleton thread-safe)."""
    with _lock:
        if "stt" not in _CACHE:
            from app.perception.stt import FasterWhisperSTT

            _CACHE["stt"] = FasterWhisperSTT()
        return _CACHE["stt"]


def get_shared_tts():
    """Retorna o KokoroTTS do processo (singleton thread-safe)."""
    with _lock:
        if "tts" not in _CACHE:
            from app.speech.tts import KokoroTTS

            _CACHE["tts"] = KokoroTTS()
        return _CACHE["tts"]


def reset_voice_providers() -> None:
    with _lock:
        _CACHE.clear()


__all__ = ["get_shared_stt", "get_shared_tts", "reset_voice_providers"]