from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class ListenerState(StrEnum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class AudioListener(ABC):
    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError


class PushToTalkAudioListener(AudioListener):
    def __init__(self) -> None:
        self.state = ListenerState.IDLE

    async def start(self) -> None:
        self.state = ListenerState.LISTENING

    async def stop(self) -> None:
        self.state = ListenerState.IDLE
