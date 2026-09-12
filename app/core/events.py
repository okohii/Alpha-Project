from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

EventHandler = Callable[["SystemEvent"], None]
_REDACT_KEYS = {"password", "passwd", "token", "api_key", "apikey", "authorization", "cookie", "secret"}
_MAX_AUDIT_EVENTS = 5000
_MAX_REPR = 512


def _redact(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in _REDACT_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, str) and len(value) > _MAX_REPR:
        return value[:_MAX_REPR] + "…"
    return value


class EventType(StrEnum):
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
    tool_selected = "tool_selected"
    tool_started = "tool_started"
    tool_finished = "tool_finished"
    tool_failed = "tool_failed"
    skill_started = "skill_started"
    skill_finished = "skill_finished"
    perception_started = "perception_started"
    perception_completed = "perception_completed"
    verification_started = "verification_started"
    verification_completed = "verification_completed"
    waiting_confirmation = "waiting_confirmation"
    waiting_confirmation_end = "waiting_confirmation_end"
    waiting_input = "waiting_input"
    permission_decision = "permission_decision"
    honesty_gate = "honesty_gate"
    textual_tool_call_blocked = "textual_tool_call_blocked"
    task_created = "task_created"
    task_step_completed = "task_step_completed"
    task_completed = "task_completed"
    task_failed = "task_failed"
    task_cancelled = "task_cancelled"
    voice_started = "voice_started"
    voice_finished = "voice_finished"
    assistant_listening = "assistant.listening"
    assistant_transcribing = "assistant.transcribing"
    assistant_thinking = "assistant.thinking"
    assistant_speaking = "assistant.speaking"


PROGRESS_EVENTS = tuple(EventType)


@dataclass(slots=True)
class SystemEvent:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int | None = None


class EventBus:
    """Barramento síncrono em processo com auditoria limitada e payload redigido."""

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
        unsubscribers = [self.subscribe(event_type, handler) for event_type in EventType]

        def unsubscribe_all() -> None:
            for unsubscribe in unsubscribers:
                unsubscribe()

        return unsubscribe_all

    def emit(self, event_type: EventType, payload: dict[str, Any] | None = None, duration_ms: int | None = None) -> None:
        safe_payload = _redact(dict(payload or {}))
        event = SystemEvent(type=event_type, payload=safe_payload, duration_ms=duration_ms)
        self._audit.append(event)
        if len(self._audit) > _MAX_AUDIT_EVENTS:
            del self._audit[:-_MAX_AUDIT_EVENTS]
        for handler in list(self._subscribers.get(event_type, [])):
            try:
                handler(event)
            except Exception:
                continue

    def clear(self) -> None:
        self._audit.clear()

    @property
    def audit(self) -> list[SystemEvent]:
        return list(self._audit)
