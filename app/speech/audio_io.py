from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_RATE = 16000
DEFAULT_TMP_PREFIX = "alpha-"


class MicrophoneRecordingError(RuntimeError):
    pass


class AudioPlaybackError(RuntimeError):
    pass


def list_microphone_devices() -> list[dict[str, Any]]:
    import sounddevice

    return [
        {"index": device["index"], "name": device["name"]}
        for device in sounddevice.query_devices()
        if device["max_input_channels"] > 0
    ]


def _resolve_device(device: str | int | None) -> int | None:
    if device is None or device == "default":
        return None
    if isinstance(device, int):
        return device
    import sounddevice

    lowered = device.lower().strip()
    matched = [
        item["index"]
        for item in sounddevice.query_devices()
        if item["max_input_channels"] > 0 and lowered in item["name"].lower()
    ]
    if not matched:
        raise MicrophoneRecordingError(f"Dispositivo de entrada não encontrado: {device}")
    return matched[0]


try:
    import webrtcvad
    _WEBRTC_VAD_AVAILABLE = True
except Exception:  # pragma: no cover
    _WEBRTC_VAD_AVAILABLE = False


def _write_wav(path: Path, frames: bytes, sample_rate: int, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)


def _record_with_key_press(device: int | None, sample_rate: int, prompt: str) -> Path:
    import sounddevice

    chunks: list[np.ndarray] = []

    def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        chunks.append(indata.copy())

    stream = sounddevice.InputStream(
        samplerate=sample_rate,
        device=device,
        channels=1,
        dtype="int16",
        callback=callback,
    )
    with stream:
        print(prompt, flush=True)
        input()
    frames = b"".join(chunk.tobytes() for chunk in chunks)
    return _save_wav(frames, sample_rate)


def _record_for_duration(duration: float, device: int | None, sample_rate: int) -> Path:
    import sounddevice

    chunks: list[np.ndarray] = []

    def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        chunks.append(indata.copy())

    stream = sounddevice.InputStream(
        samplerate=sample_rate,
        device=device,
        channels=1,
        dtype="int16",
        callback=callback,
    )
    with stream:
        deadline = time.monotonic() + duration
        print(f"▶ Gravando {duration:.0f}s...", end="", flush=True)
        while time.monotonic() < deadline:
            time.sleep(0.05)
        print(" concluído.", flush=True)
    frames = b"".join(chunk.tobytes() for chunk in chunks)
    return _save_wav(frames, sample_rate)


def _save_wav(frames: bytes, sample_rate: int) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{DEFAULT_TMP_PREFIX}rec-"))
    output_path = temp_dir / "recording.wav"
    _write_wav(output_path, frames, sample_rate)
    return output_path


def _vad_threshold(noise_floor: float, abs_threshold: float, multiplier: float) -> float:
    return max(noise_floor * multiplier, abs_threshold)


def _vad_webrtc(samples: np.ndarray, sample_rate: int, vad: Any) -> bool:
    """Detect voice activity on a valid 10/20/30 ms PCM frame."""
    try:
        if samples.dtype != np.int16:
            samples = samples.astype(np.int16)
        frame_size = int(sample_rate * 0.02)
        if samples.size < frame_size:
            return False
        frame = samples[:frame_size].tobytes()
        return bool(vad.is_speech(frame, sample_rate))
    except Exception:
        return False


def record_microphone_vad(
    device: str | int | None = None,
    sample_rate: int = SAMPLE_RATE,
    pre_roll_duration: float = 0.20,
    silence_pad: float = 0.45,
    min_speech_duration: float = 0.25,
    max_wait: float = 60.0,
    abs_threshold: float = 300.0,
    noise_floor_multiplier: float = 2.5,
    frame_duration: float = 0.05,
    speech_confirm_frames: int = 2,
    throat_clear_margin: float = 0.05,
    use_webrtc_vad: bool = False,
    on_speech_start: Callable[[], None] | None = None,
    abort_event: threading.Event | None = None,
) -> Path | None:
    """Grava fala com detecção de silêncio otimizada para baixa latência."""
    try:
        import sounddevice
    except Exception as exc:  # pragma: no cover
        raise MicrophoneRecordingError(
            "sounddevice não está disponível; instale com `pip install sounddevice`"
        ) from exc

    import math
    import queue

    device_index = _resolve_device(device)
    blocksize = max(1, int(sample_rate * frame_duration))
    frames_queue: Any = queue.Queue(maxsize=64)

    pre_roll_frames = max(1, round(pre_roll_duration / frame_duration))
    pre_roll_buffer: list[np.ndarray] = []

    webrtc_vad = None
    if use_webrtc_vad and _WEBRTC_VAD_AVAILABLE:
        try:
            webrtc_vad = webrtcvad.Vad(2)
        except Exception:
            use_webrtc_vad = False

    def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        sample = indata.flatten()
        rms = float(math.sqrt(float(np.mean(np.square(sample.astype(np.float32))))))
        try:
            frames_queue.put_nowait((rms, sample.copy()))
        except queue.Full:
            pass

    noise_samples: list[float] = []
    speech_chunks: list[np.ndarray] = []
    speech_started = False
    threshold = abs_threshold

    stream = sounddevice.InputStream(
        samplerate=sample_rate,
        device=device_index,
        channels=1,
        dtype="int16",
        blocksize=blocksize,
        callback=callback,
        latency="low",
    )
    with stream:
        confirming_frames = 0
        silent_frames = 0
        silence_frames_needed = max(1, round(silence_pad / frame_duration))
        speech_frames_min = max(1, round(min_speech_duration / frame_duration))
        speech_confirmed = max(1, int(speech_confirm_frames))
        deadline = time.monotonic() + max_wait
        while True:
            if abort_event is not None and abort_event.is_set():
                break
            try:
                rms, sample = frames_queue.get(timeout=0.08)
            except queue.Empty:
                if time.monotonic() >= deadline:
                    break
                continue

            if len(pre_roll_buffer) < pre_roll_frames:
                pre_roll_buffer.append(sample.copy())
            else:
                pre_roll_buffer.pop(0)
                pre_roll_buffer.append(sample.copy())

            if use_webrtc_vad and webrtc_vad is not None:
                is_voice = _vad_webrtc(sample, sample_rate, webrtc_vad)
            else:
                if len(noise_samples) < 4:
                    noise_samples.append(rms)
                    continue
                if len(noise_samples) == 4:
                    noise_floor = float(np.percentile(np.asarray(noise_samples), 10))
                    threshold = _vad_threshold(noise_floor, abs_threshold, noise_floor_multiplier)
                is_voice = rms >= threshold

            if not speech_started:
                confirming_frames = confirming_frames + 1 if is_voice else 0
                if confirming_frames >= speech_confirmed:
                    speech_started = True
                    silent_frames = 0
                    if on_speech_start is not None:
                        on_speech_start()
            else:
                if is_voice:
                    silent_frames = 0
                else:
                    silent_frames += 1
                    if silent_frames >= silence_frames_needed:
                        break

            if speech_started:
                speech_chunks.append(sample)

            if time.monotonic() >= deadline:
                break

    all_chunks = (pre_roll_buffer + speech_chunks) if speech_started and pre_roll_buffer else speech_chunks
    if len(all_chunks) < speech_frames_min:
        return None

    frames = b"".join(chunk.astype(np.int16).tobytes() for chunk in all_chunks)
    return _save_wav(frames, sample_rate)


def play_wav(path: Path) -> None:
    audio_path = Path(path)
    if not audio_path.exists():
        raise AudioPlaybackError(f"Áudio não encontrado: {audio_path}")

    if sys.platform == "win32":
        import winsound
        winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
        return

    for player in ("afplay", "paplay", "aplay"):
        executable = shutil.which(player)
        if executable:
            subprocess.run([executable, str(audio_path)], check=False)
            return
    raise AudioPlaybackError("Nenhum reprodutor de áudio disponível para reproduzir o WAV.")


def play_wav_async(path: Path) -> tuple[str, int, int]:
    audio_path = Path(path)
    if not audio_path.exists():
        raise AudioPlaybackError(f"Áudio não encontrado: {audio_path}")

    with wave.open(str(audio_path), "rb") as wav_file:
        frame_rate = wav_file.getframerate()
        n_frames = wav_file.getnframes()

    if sys.platform == "win32":
        import winsound
        winsound.PlaySound(str(audio_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return ("winsound", frame_rate, n_frames)

    for player in ("afplay", "paplay", "aplay"):
        executable = shutil.which(player)
        if executable:
            subprocess.Popen([executable, str(audio_path)])
            return (player, frame_rate, n_frames)
    raise AudioPlaybackError("Nenhum reprodutor de áudio disponível para reproduzir o WAV.")


def stop_wav_async(player: str) -> None:
    if player == "winsound":
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        return

    executable = shutil.which(player)
    if executable:
        subprocess.run([executable, "-stop"], check=False)
