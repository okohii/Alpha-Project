"""Avatar do ALPHA.

O avatar NÃO possui inteligência própria: é um reflexo visual do estado do
sistema. Fluxo:

    Alpha Core → EventBus → AvatarController → AvatarRenderer

O controller transforma eventos do sistema em transições de ``AvatarState``
e instruções (``AvatarCommand``) para o renderer — Live2D, 2D, 3D ou web —
que é substituível sem acoplar o agente ao avatar.

A janela (``desktop.py``) é um overlay transparente tipo "PNG flutuante",
sem moldura, com o microfone ligado por padrão (voz contínua em
``server.py``).
"""

from pathlib import Path

from app.avatar.controller import AvatarController
from app.avatar.mapping import AnimationMapping
from app.avatar.renderer import AvatarCommand, AvatarRenderer, NullRenderer
from app.avatar.server import router as avatar_router
from app.avatar.state import (
    EVENT_TO_STATE,
    SUCCESS_IDLE_DELAY_MS,
    AvatarState,
    state_for_event,
)

UI_DIR = Path(__file__).parent / "ui"

__all__ = [
    "AnimationMapping",
    "AvatarCommand",
    "AvatarController",
    "AvatarRenderer",
    "AvatarState",
    "EVENT_TO_STATE",
    "NullRenderer",
    "SUCCESS_IDLE_DELAY_MS",
    "UI_DIR",
    "avatar_router",
    "state_for_event",
]
