from __future__ import annotations

from enum import StrEnum

from app.core.events import EventType


class AvatarState(StrEnum):
    """Estados que o avatar pode refletir.

    O avatar NÃO escolhe nem decide fluxo: cada estado é consequência de um
    evento do sistema (EventBus) e vira uma animação/expressão no renderer.
    """

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


# Tempo sugerido (ms) antes de SUCCESS decair para IDLE — o renderer
# agenda o retorno; o controller fica livre de timers.
SUCCESS_IDLE_DELAY_MS = 2000


# Mapeamento EventBus → estado do avatar.
#
# Regra do "espelho": os eventos já são transitivos no sistema; o avatar
# apenas reflete. Quem emite (AgentCore, VoicePipeline) desconhece o avatar.
EVENT_TO_STATE: dict[EventType, AvatarState] = {
    EventType.assistant_listening: AvatarState.LISTENING,
    EventType.assistant_transcribing: AvatarState.PROCESSING,
    EventType.agent_started: AvatarState.PROCESSING,
    EventType.assistant_thinking: AvatarState.THINKING,
    EventType.agent_progress: AvatarState.PLANNING,
    EventType.tool_started: AvatarState.EXECUTING,
    EventType.verification_started: AvatarState.VERIFYING,
    EventType.assistant_speaking: AvatarState.SPEAKING,
    EventType.agent_finished: AvatarState.SUCCESS,
    EventType.agent_failed: AvatarState.ERROR,
    EventType.agent_cancelled: AvatarState.IDLE,
}

# Eventos de retorno da ferramenta/verificação → volta a "pensar" até o
# próximo passo (não fica preso em EXECUTING/VERIFYING).
_POST_TOOL_STATE: dict[EventType, AvatarState] = {
    EventType.tool_finished: AvatarState.THINKING,
    EventType.tool_failed: AvatarState.THINKING,
    EventType.verification_completed: AvatarState.THINKING,
}


def state_for_event(event_type: EventType) -> AvatarState | None:
    """Estado a partir de um tipo de evento (None = o avatar não muda)."""
    if event_type in _POST_TOOL_STATE:
        return _POST_TOOL_STATE[event_type]
    return EVENT_TO_STATE.get(event_type)
