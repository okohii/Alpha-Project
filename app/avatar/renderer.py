from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.avatar.state import AvatarState


@dataclass(frozen=True, slots=True)
class AvatarCommand:
    """Instrução de renderização — o que o avatar deve mostrar agora.

    ``animation``/``expression`` vêm do AnimationMapping; ``emotion`` vem do
    evento ``assistant_speaking``; ``lip_sync`` habilita sincronização labial
    enquanto fala; ``idle_after_ms`` sugere o retorno a IDLE (ex.: após
    ``success``), para o renderer agendar sem timers no controller.
    """

    state: AvatarState
    animation: str
    expression: str | None = None
    emotion: str | None = None
    lip_sync: bool = False
    idle_after_ms: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class AvatarRenderer(Protocol):
    """Backend de renderização do avatar.

    Live2D, 2D, 3D ou web: qualquer backend que implemente ``show`` é
    substituível sem tocar no controller, no agente ou no EventBus.
    O renderer recebe comandos; nunca decide estados.
    """

    def show(self, command: AvatarCommand) -> None: ...


class NullRenderer:
    """Renderer no-op: avatar desligado, mas o pipeline segue intacto."""

    def show(self, command: AvatarCommand) -> None:
        pass
