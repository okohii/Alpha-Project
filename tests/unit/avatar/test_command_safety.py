"""Segurança do comando pós-wake: evidência fraca nunca executa ação externa.

O ``command_hint`` do wake (tiny) NÃO é verdade absoluta: com a transcrição
full ruim/falha e confiança do wake insuficiente, nada é executado.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.avatar.server import _capture_kwargs, _choose_after_wake


def test_full_transcription_is_preferred_source():
    kind, text = _choose_after_wake(
        full_text="Alpha, abrir bloco de notas",
        full_confidence=0.81,
        full_suspicious=False,
        full_failed=False,
        wake_command="abrir bloco de notas",
        wake_confidence=0.74,
        min_command_confidence=0.6,
    )
    assert kind == "full"
    assert text == "Alpha, abrir bloco de notas"


def test_full_failure_with_strong_wake_confidence_uses_hint():
    kind, text = _choose_after_wake(
        full_text="",
        full_confidence=0.0,
        full_suspicious=True,
        full_failed=True,
        wake_command="abrir bloco de notas",
        wake_confidence=0.74,
        min_command_confidence=0.6,
    )
    assert kind == "hint"
    assert text == "abrir bloco de notas"


def test_full_failure_with_weak_wake_confidence_skips_action():
    kind, text = _choose_after_wake(
        full_text="",
        full_confidence=0.0,
        full_suspicious=True,
        full_failed=True,
        wake_command="abrir bloco de notas",
        wake_confidence=0.45,
        min_command_confidence=0.6,
    )
    assert kind == "skip"
    assert text == ""


def test_suspicious_full_falls_back_to_hint_only_when_strong():
    kind, text = _choose_after_wake(
        full_text="abrir",
        full_confidence=0.2,
        full_suspicious=True,
        full_failed=False,
        wake_command="abrir bloco de notas",
        wake_confidence=0.8,
        min_command_confidence=0.6,
    )
    assert kind == "hint"


def test_suspicious_full_with_weak_wake_skips():
    kind, text = _choose_after_wake(
        full_text="abrir",
        full_confidence=0.2,
        full_suspicious=True,
        full_failed=False,
        wake_command="abrir bloco de notas",
        wake_confidence=0.5,
        min_command_confidence=0.6,
    )
    assert kind == "skip"


def test_capture_kwargs_reflects_settings():
    settings = SimpleNamespace(
        stt_capture_silence_pad=0.5,
        stt_capture_min_speech_duration=0.35,
        stt_capture_abs_threshold=250.0,
        stt_capture_noise_floor_multiplier=2.2,
        stt_capture_frame_duration=0.05,
        stt_capture_speech_confirm_frames=2,
    )
    kwargs = _capture_kwargs(settings)
    assert kwargs["silence_pad"] == 0.5
    assert kwargs["abs_threshold"] == 250.0