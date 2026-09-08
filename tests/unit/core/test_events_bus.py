from __future__ import annotations

from app.core.events import EventBus, EventType, SystemEvent


def test_event_bus_subscribe_and_emit():
    bus = EventBus()
    received: list[SystemEvent] = []

    def on_event(event: SystemEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.tool_started, on_event)
    bus.emit(EventType.tool_started, {"tool": "web_search"})
    bus.emit(EventType.tool_finished, {"tool": "web_search"})

    assert len(received) == 1
    assert received[0].payload == {"tool": "web_search"}
    assert received[0].type is EventType.tool_started


def test_event_bus_unsubscribe():
    bus = EventBus()
    received: list[SystemEvent] = []
    unsubscribe = bus.subscribe(EventType.agent_started, received.append)
    bus.emit(EventType.agent_started)
    unsubscribe()
    bus.emit(EventType.agent_started)
    assert len(received) == 1


def test_event_bus_audit_records_all():
    bus = EventBus()
    bus.emit(EventType.agent_started)
    bus.emit(EventType.tool_started)
    bus.emit(EventType.agent_finished)
    assert len(bus.audit) == 3
    assert [e.type for e in bus.audit] == [
        EventType.agent_started,
        EventType.tool_started,
        EventType.agent_finished,
    ]


def test_event_bus_subscribe_all():
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe_all(received.append)
    bus.emit(EventType.agent_started)
    bus.emit(EventType.tool_finished)
    assert len(received) == 2


def test_event_bus_handler_error_does_not_break_emitter():
    bus = EventBus()

    def boom(event: SystemEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(EventType.agent_started, boom)
    bus.emit(EventType.agent_started)  # não deve propagar


def test_system_event_has_duration():
    event = SystemEvent(type=EventType.tool_finished, duration_ms=123)
    assert event.duration_ms == 123


def test_all_event_types_are_string_enum():
    for event_type in EventType:
        assert event_type.value
