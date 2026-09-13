"""E2E (mocks) do turno de voz: wake → full STT → InteractionManager → agente.

Valida o contrato do avatar sem microfone: wake aceito, comando normalizado,
agente recebe exatamente o texto do usuário e a interação retorna à escuta.
Nunca deve surgir 'não entendi' quando a ferramenta está disponível.
"""
from __future__ import annotations

from dataclasses import dataclass

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