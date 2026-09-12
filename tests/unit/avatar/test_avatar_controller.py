from __future__ import annotations

from app.avatar.controller import AvatarController
from app.avatar.renderer import AvatarCommand
from app.avatar.state import SUCCESS_IDLE_DELAY_MS, AvatarState
from app.core.events import EventBus, EventType, SystemEvent


class RecordingRenderer:
    """Renderer de teste — substituto de Live2D/2D/3D que só registra."""

    def __init__(self) -> None:
        self.commands: list[AvatarCommand] = []

    def show(self, command: AvatarCommand) -> None:
        self.commands.append(command)


def test_avatar_initial_state_is_idle():
    controller = AvatarController()
    assert controller.state is AvatarState.IDLE


def test_full_flow_transitions_to_renderer():
    renderer = RecordingRenderer()
    controller = AvatarController(renderer=renderer)

    def emit(event_type: EventType, payload: dict | None = None) -> None:
        controller.handle_event(SystemEvent(type=event_type, payload=payload))

    emit(EventType.assistant_listening)
    emit(EventType.agent_started)
    emit(EventType.agent_progress)
    emit(EventType.tool_started)
    emit(EventType.verification_started)
    emit(EventType.assistant_speaking)
    emit(EventType.agent_finished)

    assert controller.state is AvatarState.SUCCESS
    assert [command.state for command in renderer.commands] == [
        AvatarState.LISTENING,
        AvatarState.THINKING,
        AvatarState.PLANNING,
        AvatarState.EXECUTING,
        AvatarState.VERIFYING,
        AvatarState.SPEAKING,
        AvatarState.SUCCESS,
    ]


def test_success_command_carries_idle_decay_hint():
    renderer = RecordingRenderer()
    controller = AvatarController(renderer=renderer)
    controller.handle_event(SystemEvent(type=EventType.agent_finished))
    command = renderer.commands[-1]
    assert command.state is AvatarState.SUCCESS
    assert command.animation == "success"
    assert command.expression == "happy"
    assert command.idle_after_ms == SUCCESS_IDLE_DELAY_MS


def test_to_idle_returns_to_idle():
    renderer = RecordingRenderer()
    controller = AvatarController(renderer=renderer)
    controller.handle_event(SystemEvent(type=EventType.agent_finished))
    controller.to_idle()
    assert controller.state is AvatarState.IDLE
    assert renderer.commands[-1].state is AvatarState.IDLE


def test_handle_event_ignores_unknown_and_repeats():
    renderer = RecordingRenderer()
    controller = AvatarController(renderer=renderer)
    assert controller.handle_event(SystemEvent(type=EventType.user_message)) is None
    assert controller.handle_event(SystemEvent(type=EventType.token_stream)) is None

    controller.handle_event(SystemEvent(type=EventType.assistant_listening))
    assert controller.handle_event(SystemEvent(type=EventType.assistant_listening)) is None
    assert len(renderer.commands) == 1


def test_speaking_command_carries_emotion_and_lip_sync():
    renderer = RecordingRenderer()
    controller = AvatarController(renderer=renderer)
    controller.handle_event(
        SystemEvent(
            type=EventType.assistant_speaking,
            payload={"emotion": "sad", "intensity": 0.7},
        )
    )
    command = renderer.commands[-1]
    assert command.lip_sync is True
    assert command.emotion == "sad"
    assert command.animation == "speaking"


def test_renderer_error_does_not_break_pipeline():
    renderer = RecordingRenderer()
    original = renderer.show

    def boom(command: AvatarCommand) -> None:
        if command.state is AvatarState.ERROR:
            raise RuntimeError("renderer estourou")
        original(command)

    renderer.show = boom  # type: ignore[method-assign]
    controller = AvatarController(renderer=renderer)
    controller.handle_event(SystemEvent(type=EventType.agent_failed))
    assert controller.state is AvatarState.ERROR


def test_subscribe_via_event_bus():
    renderer = RecordingRenderer()
    controller = AvatarController(renderer=renderer)
    bus = EventBus()
    controller.subscribe(bus)
    bus.emit(EventType.assistant_listening)
    bus.emit(EventType.tool_started)
    bus.emit(EventType.agent_failed)
    assert controller.state is AvatarState.ERROR
    assert [command.state for command in renderer.commands] == [
        AvatarState.LISTENING,
        AvatarState.EXECUTING,
        AvatarState.ERROR,
    ]


def test_unsubscribe_stops_reacting():
    renderer = RecordingRenderer()
    controller = AvatarController(renderer=renderer)
    bus = EventBus()
    controller.subscribe(bus)
    bus.emit(EventType.agent_started)
    controller.unsubscribe()
    bus.emit(EventType.agent_failed)
    assert controller.state is AvatarState.THINKING
    assert len(renderer.commands) == 1
