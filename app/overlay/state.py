from __future__ import annotations

from app.core.events import EventType
from app.core.interaction_state import InteractionPhase, phase_for_event


# O overlay expõe apenas o subconjunto de fases relevantes à UI compacta.
OverlayState = InteractionPhase

EVENT_TO_STATE = {
    EventType.assistant_listening: OverlayState.LISTENING,
    EventType.assistant_transcribing: OverlayState.LISTENING,
    EventType.agent_started: OverlayState.THINKING,
    EventType.agent_progress: OverlayState.PLANNING,
    EventType.tool_started: OverlayState.EXECUTING,
    EventType.verification_started: OverlayState.VERIFYING,
    EventType.assistant_thinking: OverlayState.THINKING,
    EventType.assistant_speaking: OverlayState.SPEAKING,
    EventType.agent_finished: OverlayState.IDLE,
    EventType.agent_failed: OverlayState.ERROR,
    EventType.agent_cancelled: OverlayState.IDLE,
}

# Mantido para consumidores antigos que importam os mapas diretamente.
_POST_TOOL_STATE = {
    EventType.tool_finished: OverlayState.THINKING,
    EventType.tool_failed: OverlayState.THINKING,
    EventType.verification_completed: OverlayState.THINKING,
}

TOOL_EVENTS: set[EventType] = {
    EventType.tool_started,
    EventType.tool_finished,
    EventType.tool_failed,
}

TEXT_EVENTS: set[EventType] = {
    EventType.user_message,
    EventType.assistant_message,
    EventType.token_stream,
}

TERMINAL_EVENTS: set[EventType] = {
    EventType.agent_finished,
    EventType.agent_failed,
    EventType.agent_cancelled,
}


def state_for_event(event_type: EventType) -> OverlayState | None:
    """Estado canônico compartilhado, convertido para a API histórica do overlay."""
    phase = phase_for_event(event_type)
    if phase is not None:
        return phase
    return EVENT_TO_STATE.get(event_type)
