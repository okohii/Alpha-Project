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


# ---- Optional WebRTC VAD integration ----
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
            time.sleep(0.1)
        print(" concluído.", flush=True)
    frames = b"".join(chunk.tobytes() for chunk in chunks)
    return _save_wav(frames, sample_rate)


def _save_wav(frames: bytes, sample_rate: int) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{DEFAULT_TMP_PREFIX}rec-"))
    output_path = temp_dir / "recording.wav"
    _write_wav(output_path, frames, sample_rate)
    return output_path


def record_microphone(
    duration: float | None = None,
    device: str | int | None = None,
    sample_rate: int = SAMPLE_RATE,
    prompt: str = "Pressione Enter para encerrar a gravação.",
) -> Path:
    """Grava o microfone e retorna o caminho de um arquivo WAV temporário.

    Com ``duration`` grava por tempo fixo; caso contrário fica gravando até a
    tecla Enter ser pressionada.
    """
    try:
        import sounddevice  # noqa: F401
    except Exception as exc:  # pragma: no cover
        raise MicrophoneRecordingError(
            "sounddevice não está disponível; instale com `pip install sounddevice`"
        ) from exc

    device_index = _resolve_device(device)
    if duration is not None and duration > 0:
        return _record_for_duration(duration, device_index, sample_rate)
    return _record_with_key_press(device_index, sample_rate, prompt)


def _vad_threshold(noise_floor: float, abs_threshold: float, multiplier: float) -> float:
    return max(noise_floor * multiplier, abs_threshold)


def _vad_webrtc(rms_value: float, sample_rate: int, vad: Any) -> bool:
    """Detect voice activity using WebRTC VAD.

    WebRTC VAD expects amplitude-scaled integer samples in the range
    [-32768, 32767] and a frame duration of 10, 20 or 30 ms.
    """
    frame_duration_ms = 30
    frame_size = int(sample_rate * frame_duration_ms / 1000)
    # Clamp to valid WebRTC VAD levels
    amplitude = max(-32768, min(32767, int(rms_value)))
    try:
        return vad.is_speech(
            bytes([amplitude] * frame_size), sample_rate
        )
    except Exception:
        return False


def record_microphone_vad(
    device: str | int | None = None,
    sample_rate: int = SAMPLE_RATE,
    pre_roll_duration: float = 0.3,
    silence_pad: float = 0.8,
    min_speech_duration: float = 0.3,
    max_wait: float = 60.0,
    abs_threshold: float = 300.0,
    noise_floor_multiplier: float = 3.0,
    frame_duration: float = 0.1,
    speech_confirm_frames: int = 2,
    throat_clear_margin: float = 0.05,
    use_webrtc_vad: bool = False,
    on_speech_start: Callable[[], None] | None = None,
    abort_event: threading.Event | None = None,
) -> Path | None:
    """Grava até detectar o fim da fala (silêncio prolongado).

    Includes pre-ring buffer to avoid cutting the speech start.

    Retorna o caminho do WAV com a fala detectada ou ``None`` quando nada é
    falado dentro de ``max_wait`` segundos.

    ``on_speech_start`` é chamado assim que o início da fala é confirmado
    (útil para interromper uma reprodução em andamento). Quando ``abort_event``
    é fornecido e fica marcado, a gravação é encerrada o quanto antes.

    Args:
        use_webrtc_vad: Se True, usa WebRTC VAD em vez do thresholds RMS.
            Requer que o pacote ``webrtc-vad`` esteja instalado.
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
    frames_queue: Any = queue.Queue()

    # Pre-ring buffer to capture the beginning of speech and avoid cutting it.
    # Holds approximately pre_roll_duration seconds of audio before speech is detected.
    pre_roll_frames = max(1, round(pre_roll_duration / frame_duration))
    pre_roll_buffer: list[np.ndarray] = []

    # Initialize WebRTC VAD if requested
    webrtc_vad = None
    if use_webrtc_vad and _WEBRTC_VAD_AVAILABLE:
        try:
            webrtc_vad = webrtcvad.Vad(3)  # aggression mode 3 (most aggressive)
        except Exception:
            use_webrtc_vad = False

    def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        sample = indata.flatten()
        rms = float(math.sqrt(float(np.mean(np.square(sample.astype(np.float32))))))
        frames_queue.put_nowait((rms, sample.copy()))

    noise_samples: list[float] = []
    speech_chunks: list[np.ndarray] = []
    ring_buffer_full = False

    stream = sounddevice.InputStream(
        samplerate=sample_rate,
        device=device_index,
        channels=1,
        dtype="int16",
        blocksize=blocksize,
        callback=callback,
    )
    with stream:
        speech_started = False
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
                rms, sample = frames_queue.get(timeout=0.2)
            except Exception:
                if time.monotonic() >= deadline:
                    break
                continue

            # Feed pre-ring buffer regardless of speech state
            if len(pre_roll_buffer) < pre_roll_frames:
                pre_roll_buffer.append(sample.copy())
            elif not ring_buffer_full:
                # Shift buffer and add new sample (circular behavior)
                pre_roll_buffer.pop(0)
                pre_roll_buffer.append(sample.copy())
                ring_buffer_full = True

            if use_webrtc_vad and webrtc_vad is not None:
                _vad_webrtc(rms, sample_rate, webrtc_vad)
            else:
                if len(noise_samples) < 8:
                    noise_samples.append(rms)
                    continue

                if len(noise_samples) == 8:
                    noise_floor = float(np.percentile(np.asarray(noise_samples), 10))
                    threshold = _vad_threshold(noise_floor, abs_threshold, noise_floor_multiplier)

                if not speech_started:
                    confirming_frames = confirming_frames + 1 if rms >= threshold else 0
                    if confirming_frames >= speech_confirmed:
                        speech_started = True
                        silent_frames = 0
                        # Emit pre-roll captured audio as the beginning of speech
                        if on_speech_start is not None:
                            on_speech_start()
                else:
                    if rms >= threshold:
                        silent_frames = 0
                    else:
                        silent_frames += 1
                        # End of speech detected
                        if silent_frames >= silence_frames_needed:
                            break

            if speech_started:
                speech_chunks.append(sample)

            if time.monotonic() >= deadline:
                break

    # If speech was detected, prepend the pre-ring buffer to preserve the speech start
    if speech_started and pre_roll_buffer:
        all_chunks = pre_roll_buffer + speech_chunks
    else:
        all_chunks = speech_chunks

    speech_frames = len(all_chunks)
    if speech_frames < speech_frames_min:
        return None

    frames = b"".join(chunk.astype(np.int16).tobytes() for chunk in all_chunks)
    return _save_wav(frames, sample_rate)


def play_wav(path: Path) -> None:
    """Reproduz um arquivo WAV (bloqueante)."""
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
    """Inicia a reprodução de um WAV sem bloquear.

    Retorna ``(player, frame_rate, n_frames)`` para que o chamador possa
    interromper a reprodução ou aguardar a duração do áudio.
    """
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
    """Interrompe uma reprodução iniciada com ``play_wav_async``."""
    if player == "winsound":
        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        return

    executable = shutil.which(player)
    if executable:
        subprocess.run([executable, "-stop"], check=False)
