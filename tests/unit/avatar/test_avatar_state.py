from __future__ import annotations

from app.avatar.state import (
    EVENT_TO_STATE,
    SUCCESS_IDLE_DELAY_MS,
    AvatarState,
    state_for_event,
)
from app.core.events import EventType


def test_avatar_state_enum_covers_requested_states():
    expected = {
        "idle",
        "listening",
        "thinking",
        "planning",
        "executing",
        "verifying",
        "speaking",
        "success",
        "error",
    }
    assert {state.value for state in AvatarState} == expected


def test_event_mapping_core_flow():
    assert state_for_event(EventType.assistant_listening) is AvatarState.LISTENING
    assert state_for_event(EventType.assistant_transcribing) is AvatarState.LISTENING
    assert state_for_event(EventType.agent_started) is AvatarState.THINKING
    assert state_for_event(EventType.assistant_thinking) is AvatarState.THINKING
    assert state_for_event(EventType.agent_progress) is AvatarState.PLANNING
    assert state_for_event(EventType.tool_started) is AvatarState.EXECUTING
    assert state_for_event(EventType.verification_started) is AvatarState.VERIFYING
    assert state_for_event(EventType.assistant_speaking) is AvatarState.SPEAKING
    assert state_for_event(EventType.agent_finished) is AvatarState.SUCCESS
    assert state_for_event(EventType.agent_failed) is AvatarState.ERROR
    assert state_for_event(EventType.agent_cancelled) is AvatarState.IDLE


def test_agent_finished_maps_to_success_with_idle_decay():
    assert EVENT_TO_STATE[EventType.agent_finished] is AvatarState.SUCCESS
    assert SUCCESS_IDLE_DELAY_MS > 0


def test_post_tool_returns_to_thinking():
    assert state_for_event(EventType.tool_finished) is AvatarState.THINKING
    assert state_for_event(EventType.tool_failed) is AvatarState.THINKING
    assert state_for_event(EventType.verification_completed) is AvatarState.THINKING


def test_state_for_event_ignores_unknown():
    assert state_for_event(EventType.user_message) is None
    assert state_for_event(EventType.token_stream) is None
    assert state_for_event(EventType.memory_created) is None
