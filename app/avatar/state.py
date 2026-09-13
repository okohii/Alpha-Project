from __future__ import annotations

from app.core.events import EventType
from app.core.interaction_state import EVENT_TO_PHASE, InteractionPhase, phase_for_event


# O estado visual do avatar agora é a fase canônica de interação do sistema.
AvatarState = InteractionPhase

# Alias público mantido para compatibilidade com renderer, testes e integrações
# existentes. A fonte de verdade permanece em app.core.interaction_state.
EVENT_TO_STATE = EVENT_TO_PHASE

SUCCESS_IDLE_DELAY_MS = 2000


def state_for_event(event_type: EventType) -> AvatarState | None:
    """Converte a fase canônica do sistema para o estado visual do avatar."""
    return phase_for_event(event_type)


__all__ = ["AvatarState", "EVENT_TO_STATE", "SUCCESS_IDLE_DELAY_MS", "state_for_event"]
