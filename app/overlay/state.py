from __future__ import annotations

from app.core.events import EventType
from app.core.interaction_state import InteractionPhase, phase_for_event

OverlayState = InteractionPhase

# Compatibilidade para consumidores que importam o mapa. A fonte de verdade
# continua sendo core.interaction_state; diferenças são apenas de apresentação.
# agent_started marca o início do processamento do pedido: na UI isso é
# "Pensando", não "Escutando" (o core usa PROCESSING para o avatar, que tem a
# fase própria). assistant_transcribing segue ouvindo (PROCESSING->LISTENING).
EVENT_TO_STATE = {
    event: (
        OverlayState.THINKING
        if event is EventType.agent_started
        else OverlayState.LISTENING
        if phase is OverlayState.PROCESSING
        else OverlayState.IDLE
        if phase is OverlayState.SUCCESS
        else phase
    )
    for event in EventType
    if (phase := phase_for_event(event)) is not None
}

_POST_TOOL_STATE = {
    event: OverlayState.THINKING
    for event in (
        EventType.tool_finished,
        EventType.tool_failed,
        EventType.verification_completed,
    )
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
    # O overlay/desktop apresenta o início do turno como "Pensando", não
    # "Escutando": quando o agente começa, o input já foi recebido.
    if event_type is EventType.agent_started:
        return OverlayState.THINKING
    phase = phase_for_event(event_type)
    if phase is None:
        return None
    if phase is OverlayState.PROCESSING:
        return OverlayState.LISTENING
    if phase is OverlayState.SUCCESS:
        return OverlayState.IDLE
    return phase
