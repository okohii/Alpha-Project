from __future__ import annotations

from app.core.events import EventType
from app.core.interaction_state import InteractionPhase, phase_for_event


# Alias público mantido para compatibilidade do renderer/avatar.
AvatarState = InteractionPhase

SUCCESS_IDLE_DELAY_MS = 2000


def state_for_event(event_type: EventType) -> AvatarState | None:
    """Converte a fase canônica do sistema para o estado visual do avatar."""
    return phase_for_event(event_type)


__all__ = ["AvatarState", "SUCCESS_IDLE_DELAY_MS", "state_for_event"]
