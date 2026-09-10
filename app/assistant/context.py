from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from app.assistant.entities import Entity
from app.assistant.intent import Intent


@dataclass(slots=True)
class PendingClarification:
    """Esclarecimento aguardando resposta do usuário.

    Permite continuidade: a próxima mensagem preenche o slot pendente em vez
    de exigir repetir o pedido inteiro.
    """

    question: str
    reason: str
    missing: dict[str, str]  # slot -> descrição pendente
    previous_intent: Intent


class ConversationContext:
    """Memória estruturada da conversa para resolução de entidades.

    Guarda os INTENTS estruturados (não linguagem natural) e as pendências de
    esclarecimento por conversa. TTL simples para não acumular indefinidamente.
    """

    def __init__(self, history_per_conversation: int = 6) -> None:
        self.history_per_conversation = history_per_conversation
        self._intents: dict[str, deque[Intent]] = {}
        self._entities: dict[str, dict[str, Entity]] = {}
        self._pending: dict[str, PendingClarification] = {}

    def remember(self, conversation_id: str, intent: Intent, entities: dict[str, Entity]) -> None:
        if conversation_id is None:
            return
        key = str(conversation_id)
        history = self._intents.setdefault(key, deque(maxlen=self.history_per_conversation))
        history.append(intent)
        stored = self._entities.setdefault(key, {})
        for name, entity in entities.items():
            stored[name] = entity

    def previous_intents(self, conversation_id: str) -> list[Intent]:
        if conversation_id is None:
            return []
        return list(self._intents.get(conversation_id, []))

    def latest_intent(self, conversation_id: str) -> Intent | None:
        history = self.previous_intents(conversation_id)
        return history[-1] if history else None

    def entities(self, conversation_id: str) -> dict[str, Entity]:
        if conversation_id is None:
            return {}
        return dict(self._entities.get(conversation_id, {}))

    def set_pending(self, conversation_id: str, pending: PendingClarification) -> None:
        if conversation_id is not None:
            self._pending[str(conversation_id)] = pending

    def pending(self, conversation_id: str) -> PendingClarification | None:
        if conversation_id is None:
            return None
        return self._pending.get(str(conversation_id))

    def clear_pending(self, conversation_id: str) -> None:
        if conversation_id is not None:
            self._pending.pop(str(conversation_id), None)

    def to_dict(self, conversation_id: str) -> dict[str, Any]:
        return {
            "intents": [i.to_dict() for i in self.previous_intents(conversation_id)],
            "entities": {
                name: entity.to_dict()
                for name, entity in self.entities(conversation_id).items()
            },
            "pending": (
                self.pending(conversation_id).reason
                if self.pending(conversation_id)
                else None
            ),
        }