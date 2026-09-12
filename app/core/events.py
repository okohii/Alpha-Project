from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

EventHandler = Callable[["SystemEvent"], None]


class EventType(StrEnum):
    # conversa / agente
    user_message = "user_message"
    assistant_message = "assistant_message"
    agent_started = "agent_started"
    agent_progress = "agent_progress"
    agent_finished = "agent_finished"
    agent_failed = "agent_failed"
    agent_cancelled = "agent_cancelled"
    token_stream = "token_stream"
    memory_created = "memory_created"
    error = "error"
    # ferramentas / skills
    tool_selected = "tool_selected"
    tool_started = "tool_started"
    tool_finished = "tool_finished"
    tool_failed = "tool_failed"
    skill_started = "skill_started"
    skill_finished = "skill_finished"
    # percepção
    perception_started = "perception_started"
    perception_completed = "perception_completed"
    # verificação
    verification_started = "verification_started"
    verification_completed = "verification_completed"
    # fluxo / confirmação
    waiting_confirmation = "waiting_confirmation"
    waiting_confirmation_end = "waiting_confirmation_end"
    waiting_input = "waiting_input"
    permission_decision = "permission_decision"
    # honestidade / integridade da resposta final
    honesty_gate = "honesty_gate"
    textual_tool_call_blocked = "textual_tool_call_blocked"
    # tarefa
    task_created = "task_created"
    task_step_completed = "task_step_completed"
    task_completed = "task_completed"
    task_failed = "task_failed"
    task_cancelled = "task_cancelled"
    # voz
    voice_started = "voice_started"
    voice_finished = "voice_finished"
    # pipeline de voz
    assistant_listening = "assistant.listening"
    assistant_transcribing = "assistant.transcribing"
    assistant_thinking = "assistant.thinking"
    assistant_speaking = "assistant.speaking"


PROGRESS_EVENTS = (
    EventType.agent_started,
    EventType.agent_progress,
    EventType.skill_started,
    EventType.skill_finished,
    EventType.tool_selected,
    EventType.tool_started,
    EventType.tool_finished,
    EventType.tool_failed,
    EventType.perception_started,
    EventType.perception_completed,
    EventType.waiting_confirmation,
    EventType.waiting_input,
    EventType.task_created,
    EventType.task_step_completed,
    EventType.task_completed,
    EventType.task_failed,
    EventType.task_cancelled,
)


@dataclass(slots=True)
class SystemEvent:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int | None = None


class EventBus:
    """Barramento de eventos simples, em processo.

    Desacopla produtores (agente, executor, tarefa) de consumidores (CLI,
    TTS, logger): quem emite não conhece quem escuta.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventHandler]] = {}
        self._audit: list[SystemEvent] = []

    def subscribe(self, event_type: EventType, handler: EventHandler) -> Callable[[], None]:
        handlers = self._subscribers.setdefault(event_type, [])
        if handler not in handlers:
            handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._subscribers.get(event_type, []):
                self._subscribers[event_type].remove(handler)

        return unsubscribe

    def subscribe_all(self, handler: EventHandler) -> Callable[[], None]:
        """Inscreve o handler em todos os tipos de evento conhecidos."""
        unsubscribers = [
            self.subscribe(event_type, handler) for event_type in EventType
        ]

        def unsubscribe_all() -> None:
            for unsubscribe in unsubscribers:
                unsubscribe()

        return unsubscribe_all

    def emit(
        self,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        event = SystemEvent(
            type=event_type,
            payload=dict(payload or {}),
            duration_ms=duration_ms,
        )
        self._audit.append(event)
        for handler in list(self._subscribers.get(event_type, [])):
            try:
                handler(event)
            except Exception:  # pragma: no cover - consumidores não devem quebrar o emissor
                continue

    def clear(self) -> None:
        self._audit.clear()

    @property
    def audit(self) -> list[SystemEvent]:
        return list(self._audit)