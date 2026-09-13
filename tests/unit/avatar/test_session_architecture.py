from __future__ import annotations

import inspect

from app.avatar.server import AvatarSession
from app.avatar.voice_runtime import AvatarVoiceRuntime
from app.avatar.state import state_for_event
from app.core.events import EventType
from app.core.interaction_state import phase_for_event


def test_avatar_session_delegates_voice_runtime():
    assert "_run_voice" not in AvatarSession.__dict__
    assert "_speak_interruptible" not in AvatarSession.__dict__
    assert "_listen_for_interruption" not in AvatarSession.__dict__
    assert inspect.iscoroutinefunction(AvatarVoiceRuntime.run)


def test_avatar_and_overlay_use_same_canonical_event_phase():
    assert state_for_event(EventType.tool_started) == phase_for_event(EventType.tool_started)
    assert state_for_event(EventType.verification_started) == phase_for_event(EventType.verification_started)
    assert state_for_event(EventType.agent_failed) == phase_for_event(EventType.agent_failed)
