from __future__ import annotations

from app.avatar.state import AvatarState

# Animações padrão por estado. São nomes lógicos: o renderer concreto
# (Live2D, 2D, 3D, web) traduz para clips próprios.
DEFAULT_ANIMATIONS: dict[AvatarState, str] = {
    AvatarState.IDLE: "idle",
    AvatarState.LISTENING: "listening",
    AvatarState.THINKING: "thinking",
    AvatarState.PLANNING: "planning",
    AvatarState.PROCESSING: "processing",
    AvatarState.EXECUTING: "executing",
    AvatarState.VERIFYING: "verifying",
    AvatarState.SPEAKING: "speaking",
    AvatarState.COOLDOWN: "cooldown",
    AvatarState.SUCCESS: "success",
    AvatarState.ERROR: "error",
}

# Expressões padrão por estado — prepara o pipeline de expressões faciais.
DEFAULT_EXPRESSIONS: dict[AvatarState, str] = {
    AvatarState.IDLE: "neutral",
    AvatarState.LISTENING: "attentive",
    AvatarState.THINKING: "focused",
    AvatarState.PLANNING: "focused",
    AvatarState.PROCESSING: "focused",
    AvatarState.EXECUTING: "determined",
    AvatarState.VERIFYING: "checking",
    AvatarState.SPEAKING: "neutral",
    AvatarState.COOLDOWN: "neutral",
    AvatarState.SUCCESS: "happy",
    AvatarState.ERROR: "concerned",
}


class AnimationMapping:
    """Traduz AvatarState → animação/expressão para o renderer.

    As tabelas são substituíveis e parciais: um renderer Live2D pode injetar
    apenas os motions que deseja sobrescrever; o resto cai no padrão.
    """

    def __init__(
        self,
        animations: dict[AvatarState, str] | None = None,
        expressions: dict[AvatarState, str] | None = None,
    ) -> None:
        base_animations = dict(DEFAULT_ANIMATIONS)
        base_animations.update(animations or {})
        self._animations = base_animations

        base_expressions = dict(DEFAULT_EXPRESSIONS)
        base_expressions.update(expressions or {})
        self._expressions = base_expressions

    def for_state(self, state: AvatarState) -> str:
        return self._animations[state]

    def expression_for(self, state: AvatarState) -> str | None:
        return self._expressions.get(state)

    def lip_sync_enabled(self, state: AvatarState) -> bool:
        """Lip sync só faz sentido enquanto o avatar está falando."""
        return state is AvatarState.SPEAKING
