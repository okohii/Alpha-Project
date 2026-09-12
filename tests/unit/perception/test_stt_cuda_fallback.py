"""Fallback controlado e observável de CUDA no STT (#27).

Quando o carregamento do modelo CUDA falhar (ex.: cublas64_12.dll ausente),
o STT retoma com device=cpu e compute_type=int8 — sem derrubar o avatar e
sem esconder o motivo.
"""
from __future__ import annotations


class _WhisperModel:
    instances: list[tuple[str, str, str]] = []

    def __init__(self, size: str, device: str, compute_type: str) -> None:
        self.size = size
        self.device = device
        self.compute_type = compute_type
        _WhisperModel.instances.append((size, device, compute_type))

    def transcribe(self, audio, language=None, initial_prompt=None, **kwargs):
        segments = []
        return segments, type("I", (), {"language": "pt", "language_probability": 1.0})()


def test_cuda_load_failure_falls_back_to_cpu(monkeypatch):
    from app.perception.stt import FasterWhisperSTT

    stt = FasterWhisperSTT()
    stt.settings.stt_device = "cuda"
    stt.settings.stt_compute_type = "float16"

    calls = {"n": 0}

    def _failing(model_size, device, compute_type):
        calls["n"] += 1
        if device == "cuda":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return _WhisperModel(model_size, device, compute_type)

    monkeypatch.setattr("faster_whisper.WhisperModel", _failing)
    monkeypatch.setattr("app.perception.stt._determine_stt_device", lambda device: "cuda")
    monkeypatch.setattr(
        "app.perception.stt._compute_type_for_device",
        lambda compute, device: "int8" if device == "cpu" else "float16",
    )

    model = stt._load_model()

    assert model.device == "cpu"
    assert model.compute_type == "int8"
    assert calls["n"] == 2  # 1 tentativa cuda + 1 fallback cpu


def test_cpu_load_is_not_retried(monkeypatch):
    from app.perception.stt import FasterWhisperSTT

    stt = FasterWhisperSTT()
    stt.settings.stt_device = "cpu"
    calls = {"n": 0}

    def _ok(model_size, device, compute_type):
        calls["n"] += 1
        return _WhisperModel(model_size, device, compute_type)

    monkeypatch.setattr("faster_whisper.WhisperModel", _ok)
    model = stt._load_model()
    assert calls["n"] == 1
    assert model.device == "cpu"


def test_stt_logs_device_and_compute_type_on_ready(monkeypatch, caplog):
    from app.perception.stt import FasterWhisperSTT

    stt = FasterWhisperSTT()
    stt.settings.stt_device = "cpu"

    monkeypatch.setattr(
        "faster_whisper.WhisperModel",
        lambda size, device, compute_type: _WhisperModel(size, device, compute_type),
    )
    import logging

    with caplog.at_level(logging.INFO):
        stt._load_model()

    assert any("model_ready" in record.message for record in caplog.records)