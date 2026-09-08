from __future__ import annotations

import sys
import wave

import pytest

from app.speech import audio_io


def test_play_wav_missing_file_raises():
    with pytest.raises(audio_io.AudioPlaybackError):
        audio_io.play_wav("C:/tmp/não-existe-xyz.wav")


def test_play_wav_win32_uses_winsound(monkeypatch, tmp_path):
    wav_path = tmp_path / "sample.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 1600)

    calls = []

    class FakeWinsound:
        SND_FILENAME = 0

        @staticmethod
        def PlaySound(path, flags):
            calls.append((path, flags))

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winsound", FakeWinsound)

    audio_io.play_wav(wav_path)

    assert calls == [(str(wav_path), 0)]


def test_vad_threshold_uses_absolute_floor():
    assert audio_io._vad_threshold(5.0, 300.0, 3.0) == 300.0
    assert audio_io._vad_threshold(500.0, 300.0, 3.0) == 1500.0


def test_record_microphone_requires_sounddevice(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sounddevice":
            raise ImportError("sem sounddevice")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(audio_io.MicrophoneRecordingError):
        audio_io.record_microphone(duration=0.1)
    with pytest.raises(audio_io.MicrophoneRecordingError):
        audio_io.record_microphone_vad()
