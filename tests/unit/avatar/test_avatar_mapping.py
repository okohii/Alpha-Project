from __future__ import annotations

from app.avatar.mapping import AnimationMapping
from app.avatar.state import AvatarState


def test_default_mapping_covers_all_states():
    mapping = AnimationMapping()
    for state in AvatarState:
        assert mapping.for_state(state) == state.value


def test_default_mapping_named_animations():
    mapping = AnimationMapping()
    assert mapping.for_state(AvatarState.SPEAKING) == "speaking"
    assert mapping.for_state(AvatarState.EXECUTING) == "executing"
    assert mapping.for_state(AvatarState.SUCCESS) == "success"
    assert mapping.for_state(AvatarState.ERROR) == "error"


def test_lip_sync_only_while_speaking():
    mapping = AnimationMapping()
    assert mapping.lip_sync_enabled(AvatarState.SPEAKING) is True
    assert mapping.lip_sync_enabled(AvatarState.THINKING) is False
    assert mapping.lip_sync_enabled(AvatarState.IDLE) is False


def test_expressions_per_state():
    mapping = AnimationMapping()
    assert mapping.expression_for(AvatarState.SUCCESS) == "happy"
    assert mapping.expression_for(AvatarState.ERROR) == "concerned"
    assert mapping.expression_for(AvatarState.LISTENING) == "attentive"


def test_partial_custom_mapping_overrides_defaults():
    mapping = AnimationMapping(
        animations={AvatarState.SPEAKING: "talk"},
        expressions={AvatarState.SPEAKING: "soft"},
    )
    assert mapping.for_state(AvatarState.SPEAKING) == "talk"
    assert mapping.expression_for(AvatarState.SPEAKING) == "soft"
    assert mapping.for_state(AvatarState.IDLE) == "idle"
    assert mapping.expression_for(AvatarState.IDLE) == "neutral"
