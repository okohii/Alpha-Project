from __future__ import annotations

from enum import StrEnum

from app.core.events import EventType


class OverlayState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SPEAKING = "speaking"
    ERROR = "error"


# Mapeamento EventBus → estado do overlay.
#
# Regra: eventos são transitivos (o próximo evento pode sobrescrever o
# estado). Estados "de borda" (LISTENING/THINKING/EXECUTING etc.) são
# inferidos dos eventos que o AgentCore já emite — o overlay NÃO decide
# nada sobre o fluxo do agente, apenas reflete.
EVENT_TO_STATE: dict[EventType, OverlayState] = {
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

# Eventos que representam retorno da ferramenta → voltam a "pensar" até o
# próximo passo (não ficam presos em EXECUTING).
_POST_TOOL_STATE: dict[EventType, OverlayState] = {
    EventType.tool_finished: OverlayState.THINKING,
    EventType.tool_failed: OverlayState.THINKING,
    EventType.verification_completed: OverlayState.THINKING,
}

# Eventos que carregam nome de ferramenta para exibir no rodapé.
TOOL_EVENTS: set[EventType] = {
    EventType.tool_started,
    EventType.tool_finished,
    EventType.tool_failed,
}

# Eventos que carregam texto para o histórico.
TEXT_EVENTS: set[EventType] = {
    EventType.user_message,
    EventType.assistant_message,
    EventType.token_stream,
}

# Eventos terminais de uma rodada: o overlay deve liberar o input.
TERMINAL_EVENTS: set[EventType] = {
    EventType.agent_finished,
    EventType.agent_failed,
    EventType.agent_cancelled,
}


def state_for_event(event_type: EventType) -> OverlayState | None:
    """Estado a partir de um tipo de evento (None = não muda o estado)."""
    if event_type in _POST_TOOL_STATE:
        return _POST_TOOL_STATE[event_type]
    return EVENT_TO_STATE.get(event_type)