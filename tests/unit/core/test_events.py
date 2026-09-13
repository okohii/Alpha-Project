from __future__ import annotations

from app.core.events import EventBus, EventType


def test_event_bus_redacts_sensitive_keys_and_bounds_audit():
    bus = EventBus()
    bus.emit(
        EventType.tool_started,
        {
            "tool": "example",
            "arguments": {
                "api_key": "secret-value",
                "nested": {"token": "nested-secret"},
            },
        },
    )
    payload = bus.audit[-1].payload
    assert payload["arguments"]["api_key"] == "[REDACTED]"
    assert payload["arguments"]["nested"]["token"] == "[REDACTED]"

    for index in range(5100):
        bus.emit(EventType.agent_progress, {"i": index})
    assert len(bus.audit) == 5000
    assert bus.audit[0].payload["i"] == 100
