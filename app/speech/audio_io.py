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


def record_microphone_vad(
    device: str | int | None = None,
    sample_rate: int = SAMPLE_RATE,
    silence_pad: float = 1.2,
    min_speech_duration: float = 0.4,
    max_wait: float = 60.0,
    abs_threshold: float = 300.0,
    noise_floor_multiplier: float = 3.0,
    frame_duration: float = 0.1,
    speech_confirm_frames: int = 2,
    on_speech_start: Callable[[], None] | None = None,
    abort_event: threading.Event | None = None,
) -> Path | None:
    """Grava até detectar o fim da fala (silêncio prolongado).

    Retorna o caminho do WAV com a fala detectada ou ``None`` quando nada é
    falado dentro de ``max_wait`` segundos.

    ``on_speech_start`` é chamado assim que o início da fala é confirmado
    (útil para interromper uma reprodução em andamento). Quando ``abort_event``
    é fornecido e fica marcado, a gravação é encerrada o quanto antes.
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

    def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        sample = indata.flatten()
        rms = float(math.sqrt(float(np.mean(np.square(sample.astype(np.float32))))))
        frames_queue.put_nowait((rms, sample.copy()))

    noise_samples: list[float] = []
    speech_chunks: list[np.ndarray] = []

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
        silence_frames_needed = max(1, int(silence_pad / frame_duration))
        speech_frames_min = max(1, int(min_speech_duration / frame_duration))
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
                    if on_speech_start is not None:
                        on_speech_start()
            else:
                if rms >= threshold:
                    silent_frames = 0
                else:
                    silent_frames += 1
                    if silent_frames >= silence_frames_needed:
                        break

            if speech_started:
                speech_chunks.append(sample)

            if time.monotonic() >= deadline:
                break

    speech_frames = len(speech_chunks)
    if speech_frames < speech_frames_min:
        return None

    frames = b"".join(chunk.astype(np.int16).tobytes() for chunk in speech_chunks)
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
