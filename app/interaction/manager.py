from __future__ import annotations

import re
import time
from dataclasses import dataclass

from app.perception.wakeword import find_wake_word, normalize, strip_wake_word


@dataclass(frozen=True)
class InteractionDecision:
    accepted: bool
    activated: bool = False
    ended: bool = False
    command: str = ""
    wake_word: str | None = None
    reason: str = ""


class InteractionManager:
    """Deterministic gate between microphone transcription and AgentCore.

    Wake word starts a session. Once active, commands do not need the wake word.
    An explicit end phrase or inactivity timeout returns the session to dormant.
    """

    def __init__(self, *, enabled: bool, wake_words: str, timeout_seconds: float = 25.0,
                 end_words: str = "sair,encerrar,parar,fechar,descansar,até mais") -> None:
        self.enabled = enabled
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._wake_words = wake_words
        self._end_words = {
            normalize(x) for x in str(end_words).split(",") if normalize(x)
        }
        self.active = not enabled
        self.last_activity = time.monotonic() if self.active else 0.0

    @property
    def state(self) -> str:
        return "active" if self.active else "dormant"

    def _is_end(self, text: str) -> bool:
        cleaned = normalize(text).strip(" .,!?;:")
        if cleaned in self._end_words:
            return True
        return any(re.fullmatch(rf"(?:.*\s)?{re.escape(word)}(?:\s.*)?", cleaned) for word in self._end_words)

    def decide(self, text: str) -> InteractionDecision:
        raw = (text or "").strip()
        if not raw:
            return InteractionDecision(False, reason="empty")

        if not self.enabled:
            self.last_activity = time.monotonic()
            return InteractionDecision(True, command=raw, reason="wake_word_disabled")

        if self.active:
            if self._is_end(raw):
                self.active = False
                self.last_activity = 0.0
                return InteractionDecision(False, ended=True, reason="end_word")
            self.last_activity = time.monotonic()
            return InteractionDecision(True, command=raw, reason="active_session")

        found, command = strip_wake_word(raw, self._wake_words)
        if not found:
            return InteractionDecision(False, reason="wake_word_missing")
        self.active = True
        self.last_activity = time.monotonic()
        return InteractionDecision(True, activated=True, command=command, wake_word=find_wake_word(raw, self._wake_words), reason="wake_word")

    def expired(self, now: float | None = None) -> bool:
        if not self.enabled or not self.active:
            return False
        current = time.monotonic() if now is None else now
        return current - self.last_activity >= self.timeout_seconds

    def expire(self) -> None:
        self.active = False
        self.last_activity = 0.0
