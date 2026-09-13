from __future__ import annotations

from enum import StrEnum

from app.core.events import EventType


class InteractionPhase(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    PLANNING = "planning"
    PROCESSING = "processing"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SPEAKING = "speaking"
    COOLDOWN = "cooldown"
    SUCCESS = "success"
    ERROR = "error"


EVENT_TO_PHASE: dict[EventType, InteractionPhase] = {
    EventType.assistant_listening: InteractionPhase.LISTENING,
    EventType.assistant_transcribing: InteractionPhase.PROCESSING,
    EventType.agent_started: InteractionPhase.PROCESSING,
    EventType.assistant_thinking: InteractionPhase.THINKING,
    EventType.agent_progress: InteractionPhase.PLANNING,
    EventType.tool_started: InteractionPhase.EXECUTING,
    EventType.verification_started: InteractionPhase.VERIFYING,
    EventType.assistant_speaking: InteractionPhase.SPEAKING,
    EventType.agent_finished: InteractionPhase.SUCCESS,
    EventType.agent_failed: InteractionPhase.ERROR,
    EventType.agent_cancelled: InteractionPhase.IDLE,
}

POST_TOOL_PHASE: dict[EventType, InteractionPhase] = {
    EventType.tool_finished: InteractionPhase.THINKING,
    EventType.tool_failed: InteractionPhase.THINKING,
    EventType.verification_completed: InteractionPhase.THINKING,
}


def phase_for_event(event_type: EventType) -> InteractionPhase | None:
    return POST_TOOL_PHASE.get(event_type) or EVENT_TO_PHASE.get(event_type)
