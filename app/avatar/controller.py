from __future__ import annotations

import logging
from collections.abc import Callable

from app.avatar.mapping import AnimationMapping
from app.avatar.renderer import AvatarCommand, AvatarRenderer, NullRenderer
from app.avatar.state import (
    SUCCESS_IDLE_DELAY_MS,
    AvatarState,
    state_for_event,
)
from app.core.events import EventBus, SystemEvent

logger = logging.getLogger("app.avatar.controller")


class AvatarController:
    """Controla o avatar reagindo ao EventBus.

    O avatar NÃO tem inteligência própria: cada evento do sistema vira uma
    transição de estado e uma instrução (AvatarCommand) para o renderer.
    O controller não decide fluxo, segurança nem conteúdo — apenas reflete o
    que já foi decidido a montante.
    """

    def __init__(
        self,
        renderer: AvatarRenderer | None = None,
        mapping: AnimationMapping | None = None,
    ) -> None:
        self._renderer: AvatarRenderer = renderer if renderer is not None else NullRenderer()
        self._mapping = mapping or AnimationMapping()
        self._state = AvatarState.IDLE
        self._transitions: list[AvatarState] = [AvatarState.IDLE]
        self._unsubscribe: Callable[[], None] | None = None

    @property
    def state(self) -> AvatarState:
        return self._state

    @property
    def transitions(self) -> list[AvatarState]:
        return list(self._transitions)

    def handle_event(self, event: SystemEvent) -> AvatarState | None:
        """Aplica um evento do sistema. Retorna o novo estado (None = sem mudança)."""
        new_state = state_for_event(event.type)
        if new_state is None or new_state is self._state:
            return None
        self._transition(new_state, event)
        return new_state

    def to_idle(self) -> None:
        """Força o retorno a IDLE (ex.: fim da animação de sucesso no renderer)."""
        self._transition(AvatarState.IDLE)

    def subscribe(self, event_bus: EventBus) -> None:
        if self._unsubscribe is not None:
            raise RuntimeError("AvatarController já inscrito no EventBus")
        self._unsubscribe = event_bus.subscribe_all(self.handle_event)

    def unsubscribe(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _transition(self, new_state: AvatarState, event: SystemEvent | None = None) -> None:
        previous = self._state
        self._state = new_state
        self._transitions.append(new_state)

        payload = dict(event.payload or {}) if event is not None else {}
        command = AvatarCommand(
            state=new_state,
            animation=self._mapping.for_state(new_state),
            expression=self._mapping.expression_for(new_state),
            emotion=self._emotion_from(event, new_state),
            lip_sync=self._mapping.lip_sync_enabled(new_state),
            idle_after_ms=(SUCCESS_IDLE_DELAY_MS if new_state is AvatarState.SUCCESS else None),
            payload=payload,
        )
        try:
            self._renderer.show(command)
        except Exception:  # noqa: BLE001 - renderer nunca quebra o pipeline
            logger.exception("[avatar] renderer falhou na transição %s -> %s", previous, new_state)

    @staticmethod
    def _emotion_from(event: SystemEvent | None, state: AvatarState) -> str | None:
        if state is not AvatarState.SPEAKING or event is None:
            return None
        emotion = (event.payload or {}).get("emotion")
        return emotion if isinstance(emotion, str) else None
