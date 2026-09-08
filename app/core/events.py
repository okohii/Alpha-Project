from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    user_message = "user_message"
    assistant_message = "assistant_message"
    tool_started = "tool_started"
    tool_finished = "tool_finished"
    memory_created = "memory_created"
    voice_started = "voice_started"
    voice_finished = "voice_finished"
    error = "error"


@dataclass(slots=True)
class SystemEvent:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
