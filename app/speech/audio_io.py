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
    pre_roll_duration: float = 0.35,
    silence_pad: float = 1.25,
    min_speech_duration: float = 0.35,
    max_wait: float = 60.0,
    abs_threshold: float = 250.0,
    noise_floor_multiplier: float = 2.2,
    frame_duration: float = 0.05,
    speech_confirm_frames: int = 2,
    throat_clear_margin: float = 0.05,
    use_webrtc_vad: bool = False,
    on_speech_start: Callable[[], None] | None = None,
    abort_event: threading.Event | None = None,
) -> Path | None:
    """Grava fala com VAD tolerante a pausas naturais e protege a cauda da frase.

    A calibração inicial é determinística e a captura falha rapidamente se o
    callback do dispositivo não entregar nenhum frame. Isso evita a aparência
    de que o ALPHA está travado quando o problema real é o dispositivo/driver.
    """
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
    frames_queue: Any = queue.Queue(maxsize=128)
    callback_started = threading.Event()
    callback_error: list[str] = []
    callback_count = 0
    callback_count_lock = threading.Lock()

    pre_roll_frames = max(1, round(pre_roll_duration / frame_duration))
    pre_roll_buffer: list[np.ndarray] = []

    webrtc_vad = None
    if use_webrtc_vad and _WEBRTC_VAD_AVAILABLE:
        try:
            webrtc_vad = webrtcvad.Vad(2)
        except Exception:
            use_webrtc_vad = False

    def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        nonlocal callback_count
        callback_started.set()
        with callback_count_lock:
            callback_count += 1
        if status:
            status_text = str(status)
            if len(callback_error) < 3:
                callback_error.append(status_text)
            print(f"[audio] callback_status={status_text}", flush=True)
        try:
            sample = indata.flatten()
            rms = float(math.sqrt(float(np.mean(np.square(sample.astype(np.float32))))))
            frames_queue.put_nowait((rms, sample.copy()))
        except queue.Full:
            pass
        except Exception as exc:
            if len(callback_error) < 3:
                callback_error.append(str(exc))
            print(f"[audio] callback_error={exc}", flush=True)

    speech_chunks: list[np.ndarray] = []
    speech_started = False
    speech_started_at: float | None = None
    threshold = abs_threshold
    trailing_threshold = abs_threshold * 0.72
    pre_roll_at_start: list[np.ndarray] = []

    calibration_frames_needed = max(4, round(0.30 / frame_duration))
    calibration_rms: list[float] = []

    stream = sounddevice.InputStream(
        samplerate=sample_rate,
        device=device_index,
        channels=1,
        dtype="int16",
        blocksize=blocksize,
        callback=callback,
    )
    capture_started_at = time.monotonic()
    print(
        f"[audio] listening device={device_index if device_index is not None else 'default'} "
        f"sample_rate={sample_rate} frame={frame_duration:.2f}s",
        flush=True,
    )
    try:
        with stream:
            confirming_frames = 0
            silent_frames = 0
            silence_frames_needed = max(1, round(silence_pad / frame_duration))
            speech_frames_min = max(1, round(min_speech_duration / frame_duration))
            speech_confirmed = max(1, int(speech_confirm_frames))
            deadline = time.monotonic() + max_wait
            calibration_complete = False
            callback_deadline = time.monotonic() + 2.0

            while True:
                if abort_event is not None and abort_event.is_set():
                    break
                if not callback_started.is_set() and time.monotonic() >= callback_deadline:
                    detail = "; ".join(callback_error) if callback_error else "nenhum frame recebido do dispositivo"
                    raise MicrophoneRecordingError(
                        f"microfone não entregou áudio em 2s ({detail})"
                    )
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

                if not calibration_complete and not use_webrtc_vad:
                    calibration_rms.append(rms)
                    if len(calibration_rms) >= calibration_frames_needed:
                        noise_floor = float(
                            np.percentile(np.asarray(calibration_rms, dtype=np.float32), 10)
                        )
                        threshold = _vad_threshold(
                            noise_floor, abs_threshold, noise_floor_multiplier
                        )
                        trailing_threshold = max(
                            abs_threshold * 0.60,
                            noise_floor * 1.55,
                        )
                        calibration_complete = True
                        print(
                            f"[audio] calibration_done noise_floor={noise_floor:.1f} "
                            f"threshold={threshold:.1f} trailing_threshold={trailing_threshold:.1f}",
                            flush=True,
                        )
                    continue

                if use_webrtc_vad and webrtc_vad is not None:
                    is_voice = _vad_webrtc(sample, sample_rate, webrtc_vad)
                else:
                    is_voice = rms >= (
                        trailing_threshold if speech_started else threshold
                    )

                if not speech_started:
                    confirming_frames = confirming_frames + 1 if is_voice else 0
                    if confirming_frames >= speech_confirmed:
                        speech_started = True
                        speech_started_at = time.monotonic()
                        silent_frames = 0
                        pre_roll_at_start = [chunk.copy() for chunk in pre_roll_buffer]
                        speech_chunks = [sample.copy()]
                        print(
                            f"[audio] speech_start rms={rms:.1f} threshold={threshold:.1f}",
                            flush=True,
                        )
                        if on_speech_start is not None:
                            on_speech_start()
                else:
                    if is_voice:
                        silent_frames = 0
                    else:
                        silent_frames += 1
                        speech_duration = time.monotonic() - (
                            speech_started_at or time.monotonic()
                        )
                        if (
                            silent_frames >= silence_frames_needed
                            and speech_duration >= min_speech_duration
                        ):
                            break
                    speech_chunks.append(sample.copy())

                if time.monotonic() >= deadline:
                    break
    except MicrophoneRecordingError:
        raise
    except Exception as exc:
        raise MicrophoneRecordingError(f"falha ao capturar microfone: {exc}") from exc

    if not speech_started or len(speech_chunks) < speech_frames_min:
        logger_duration = time.monotonic() - capture_started_at
        with callback_count_lock:
            received = callback_count
        print(
            f"[audio] capture_discarded duration={logger_duration:.2f}s "
            f"speech_started={speech_started} calibrated={calibration_complete} "
            f"callbacks={received}",
            flush=True,
        )
        return None

    all_chunks = pre_roll_at_start + speech_chunks
    frames = b"".join(chunk.astype(np.int16).tobytes() for chunk in all_chunks)
    duration = len(frames) / (2 * sample_rate)
    print(
        f"[audio] captured={duration:.2f}s speech_frames={len(speech_chunks)} "
        f"threshold={threshold:.1f} trailing_threshold={trailing_threshold:.1f} "
        f"silence_pad={silence_pad:.2f}s",
        flush=True,
    )
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
