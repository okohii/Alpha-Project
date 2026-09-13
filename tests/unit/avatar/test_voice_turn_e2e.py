"""E2E (mocks) do turno de voz: wake → full STT → InteractionManager → agente.

Valida o contrato do avatar sem microfone: wake aceito, comando normalizado,
agente recebe exatamente o texto do usuário e a interação retorna à escuta.
Nunca deve surgir 'não entendi' quando a ferramenta está disponível.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.avatar.server import _choose_after_wake
from app.interaction import InteractionManager


@dataclass
class SttResult:
    text: str
    confidence: float = 0.9
    suspicious: bool = False


class FakePipeline:
    """Pipeline fake: devolve transcrições pré-programadas (wake + full)."""

    def __init__(self, wake_text: str, full_text: str) -> None:
        self.wake_text = wake_text
        self.full_text = full_text
        self.process_calls = 0

    async def process_wake(self, path):
        return {"transcription": self.wake_text, "confidence": 0.8, "is_suspicious": False}

    async def process(self, path):
        self.process_calls += 1
        return {"transcription": self.full_text, "confidence": 0.9, "is_suspicious": False}


class FakeAgent:
    def __init__(self) -> None:
        self.received: list[str] = []

    async def chat(self, command, conversation_id=None):
        self.received.append(command)
        return {"response": "Abri o bloco de notas.", "conversation_id": "c1"}


@pytest.mark.anyio
async def test_voice_turn_wake_full_to_agent_and_back():
    pipeline = FakePipeline("Alfa, abrir o bloco de notas.", "Alfa, abrir o bloco de notas.")
    manager = InteractionManager(enabled=True, wake_words="Alpha, alpha, Alfa, alfa")
    agent = FakeAgent()

    # 1) Wake (sessão dormente)
    wake = await pipeline.process_wake("x")
    from app.perception.wakeword import find_wake_word

    assert find_wake_word(wake["transcription"], manager._wake_words) is not None

    # 2) Full STT + decisão segura
    full = await pipeline.process("x")
    kind, text = _choose_after_wake(
        full_text=full["transcription"],
        full_confidence=full["confidence"],
        full_suspicious=full["is_suspicious"],
        full_failed=False,
        wake_command=wake["transcription"],
        wake_confidence=wake["confidence"],
        min_command_confidence=0.6,
    )
    assert kind == "full"

    # 3) InteractionManager: sessão ativa já aceita; prefixo é removido.
    manager.decide("alfa")  # ativa
    decision = manager.decide(text)
    assert decision.accepted is True
    command = decision.command.strip(" .,!?;:")

    # 4) Agente recebe exatamente o comando (sem wake word).
    result = await agent.chat(command)
    assert command == "abrir o bloco de notas"
    assert "não entendi" not in result["response"]
    assert agent.received == ["abrir o bloco de notas"]
    assert pipeline.process_calls == 1  # full STT uma única vez por turno


def test_voice_command_with_weak_wake_is_never_executed():
    kind, text = _choose_after_wake(
        full_text="",
        full_confidence=0.0,
        full_suspicious=True,
        full_failed=True,
        wake_command="abrir o bloco de notas",
        wake_confidence=0.4,
        min_command_confidence=0.6,
    )
    assert kind == "skip"
    assert text == ""  # evidência fraca nunca vira execução


class FallbackPipeline:
    """Pipeline fake para exercitar o fallback de wake no loop de voz."""

    def __init__(self, wake_text: str, full_text: str) -> None:
        self.wake_text = wake_text
        self.full_text = full_text
        self.process_calls = 0

    async def warmup(self, *, wake_word: bool = False, tts: bool = False) -> None:
        return None

    async def process_wake(self, path):
        return {"transcription": self.wake_text, "confidence": 0.7, "is_suspicious": False}

    async def process(self, path):
        self.process_calls += 1
        return {"transcription": self.full_text, "confidence": 0.85, "is_suspicious": False}

    async def speak_expressive(self, text, *, emotion=None):
        return {"status": "text_only", "detail": "teste", "text": text}


class FallbackAgent:
    def __init__(self) -> None:
        self.received: list[str] = []

    async def chat(self, command, conversation_id=None):
        self.received.append(command)
        return {"response": "Abri o bloco de notas.", "conversation_id": "c1"}


def _patch_runtime(monkeypatch, *, pipeline, agent):
    """Instala os mocks usados pelo AvatarVoiceRuntime.run."""
    import app.avatar.voice_runtime as voice_runtime
    from app.core.config import get_settings

    settings = get_settings()
    settings.stt_enabled = True
    settings.wake_word_enabled = True
    settings.wake_words = "Alpha, alpha, Alfa, alfa"
    settings.wake_command_min_confidence = 0.60

    calls = {"n": 0}

    def fake_record(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return Path("fake.wav")
        raise voice_runtime.audio_io.MicrophoneRecordingError("fim de teste")

    class FakeSession:
        def __init__(self) -> None:
            from app.core.events import EventBus

            self.event_bus = EventBus()
            self.cancel_event = asyncio.Event()
            self._audio_abort = threading.Event()
            self._interrupt_abort = threading.Event()
            self.conversation_id: str | None = None
            self._confirm_queue: asyncio.Queue[bool] = asyncio.Queue()
            self._interaction = None
            self.push_queue: list[dict] = []

        @property
        def state(self) -> str:
            return "idle"

        async def push(self, payload: dict) -> None:
            self.push_queue.append(payload)

        async def set_interaction(self, active: bool, reason: str = "") -> None:
            return None

        async def queue_payload(self, payload: dict) -> None:
            return None

    @asynccontextmanager
    async def fake_db_session():
        yield object()

    async def fake_build_agent(*args, **kwargs):
        return agent

    monkeypatch.setattr(voice_runtime, "build_agent", fake_build_agent)
    monkeypatch.setattr(voice_runtime.audio_io, "record_microphone_vad", fake_record)
    monkeypatch.setattr(voice_runtime, "AsyncSessionLocal", fake_db_session)
    monkeypatch.setattr(voice_runtime, "VoicePipeline", lambda *a, **kw: pipeline)

    session = FakeSession()
    runtime = voice_runtime.AvatarVoiceRuntime(session)
    return session, runtime


@pytest.mark.anyio
async def test_wake_fallback_full_stt_confirms_command(monkeypatch):
    """Tiny derruba 'Alpha' (Alza...) mas a STT full confirma: o turno segue."""

    pipeline = FallbackPipeline("Alza abrir bloco de notas.", "Alpha, abrir bloco de notas.")
    agent = FallbackAgent()
    session, runtime = _patch_runtime(monkeypatch, pipeline=pipeline, agent=agent)

    await runtime.run()

    assert agent.received == ["abrir bloco de notas"]
    captions = [m["text"] for m in session.push_queue if m.get("type") == "caption"]
    assert "Abri o bloco de notas." in captions
    assert "Pode repetir?" not in captions


@pytest.mark.anyio
async def test_wake_fallback_still_missing_asks_to_repeat(monkeypatch):
    """Nenhum modelo acha a wake word: feedback 'Pode repetir?' em vez de silêncio."""

    pipeline = FallbackPipeline("Alza.", "Alza.")
    agent = FallbackAgent()
    session, runtime = _patch_runtime(monkeypatch, pipeline=pipeline, agent=agent)

    await runtime.run()

    assert agent.received == []
    assert "Pode repetir?" in [m["text"] for m in session.push_queue if m.get("type") == "caption"]