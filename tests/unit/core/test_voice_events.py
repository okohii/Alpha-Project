from __future__ import annotations

from app.core.events import EventBus, EventType, SystemEvent


def test_event_bus_voice_events_exist():
    """All voice-related event types are registered."""
    voice_events = [
        EventType.assistant_listening,
        EventType.assistant_transcribing,
        EventType.assistant_thinking,
        EventType.assistant_speaking,
    ]
    for event_type in voice_events:
        assert event_type.value is not None
        assert isinstance(event_type, EventType.EventType)


def test_emit_assistant_listening():
    """Test emitting assistant.listening event."""
    bus = EventBus()
    received: list[SystemEvent] = []

    def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.assistant_listening, on_event)
    bus.emit(EventType.assistant_listening)
    assert len(received) == 1
    assert received[0].type is EventType.assistant_listening


def test_emit_assistant_transcribing():
    """Test emitting assistant.transcribing event."""
    bus = EventBus()
    received: list[SystemEvent] = []

    def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.assistant_transcribing, on_event)
    bus.emit(EventType.assistant_transcribing)
    assert len(received) == 1
    assert received[0].type is EventType.assistant_transcribing


def test_emit_assistant_thinking():
    """Test emitting assistant.thinking event."""
    bus = EventBus()
    received: list[SystemEvent] = []

    def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.assistant_thinking, on_event)
    bus.emit(EventType.assistant_thinking)
    assert len(received) == 1
    assert received[0].type is EventType.assistant_thinking


def test_emit_assistant_speaking():
    """Test emitting assistant.speaking event."""
    bus = EventBus()
    received: list[SystemEvent] = []

    def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.assistant_speaking, on_event)
    bus.emit(EventType.assistant_speaking)
    assert len(received) == 1
    assert received[0].type is EventType.assistant_speaking


def test_all_voice_events_emit_payload():
    """Test that voice events can carry payload."""
    bus = EventBus()

    # Test assistant.listening with payload
    bus.emit(EventType.assistant_listening, {"status": "started"})
    received = []
    def on_listen(e): received.append(e)
    bus.subscribe(EventType.assistant_listening, on_listen)
    bus.emit(EventType.assistant_listening, {"status": "started"})
    assert received[0].payload == {"status": "started"}

    # Test assistant.speaking with payload
    bus.emit(EventType.assistant_speaking, {"text": "hello", "audio_path": "/tmp/a.wav"})
    received.clear()
    def on_speak(e): received.append(e)
    bus.subscribe(EventType.assistant_speaking, on_speak)
    bus.emit(EventType.assistant_speaking, {"text": "hello", "audio_path": "/tmp/a.wav"})
    assert received[0].payload == {"text": "hello", "audio_path": "/tmp/a.wav"}