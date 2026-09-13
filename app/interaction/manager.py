from __future__ import annotations

import time
from dataclasses import dataclass

from app.perception.wakeword import find_wake_word, normalize, strip_wake_prefix


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

    The inactivity timeout is armed only after ALPHA finishes speaking. Time
    spent waiting for the user, processing a command, or generating speech
    never consumes the 25-second inactivity window.
    """

    def __init__(self, *, enabled: bool, wake_words: str, timeout_seconds: float = 25.0,
                 end_words: str = "sair,encerrar,parar,fechar,descansar,até mais") -> None:
        self.enabled = enabled
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._wake_words = wake_words
        self._end_words = {normalize(x) for x in str(end_words).split(",") if normalize(x)}
        self.active = not enabled
        self.last_activity = 0.0
        self._timeout_armed = False

    @property
    def state(self) -> str:
        return "active" if self.active else "dormant"

    def _is_end(self, text: str) -> bool:
        cleaned = normalize(text).strip(" .,!?;:")
        if cleaned in self._end_words:
            return True
        explicit_phrases = {
            "pode encerrar a interacao", "pode encerrar a interação",
            "encerre a interacao", "encerre a interação",
            "quero encerrar a interacao", "quero encerrar a interação",
            "encerrar o modo de interacao", "encerrar o modo de interação",
        }
        return cleaned in explicit_phrases

    def decide(self, text: str) -> InteractionDecision:
        raw = (text or "").strip()
        if not raw:
            return InteractionDecision(False, reason="empty")
        if not self.enabled:
            self.active = True
            self._timeout_armed = False
            return InteractionDecision(True, command=raw, reason="wake_word_disabled")
        if self.active:
            if self._is_end(raw):
                self.active = False
                self.last_activity = 0.0
                self._timeout_armed = False
                return InteractionDecision(False, ended=True, reason="end_word")
            # User activity never starts/restarts the timeout. It is armed only
            # by touch_activity(), called after ALPHA finishes speaking.
            self._timeout_armed = False
            # Mesmo em sessão ativa, um wake word repetido no início da frase
            # é removido antes de seguir para o Agent (não vira instrução).
            _, command = strip_wake_prefix(raw, self._wake_words)
            command = command.strip(" .,!?;:\n\t")
            return InteractionDecision(True, command=command, reason="active_session")
        found, command = strip_wake_prefix(raw, self._wake_words)
        if not found:
            return InteractionDecision(False, reason="wake_word_missing")
        self.active = True
        self.last_activity = 0.0
        self._timeout_armed = False
        command = command.strip(" .,!?;:\n\t")
        if not command:
            return InteractionDecision(False, activated=True, command="", wake_word=find_wake_word(raw, self._wake_words), reason="wake_word_only")
        return InteractionDecision(True, activated=True, command=command, wake_word=find_wake_word(raw, self._wake_words), reason="wake_word")

    def touch_activity(self) -> None:
        """Arm/restart the inactivity timeout after ALPHA finishes speaking."""
        if self.active:
            self.last_activity = time.monotonic()
            self._timeout_armed = True

    def expired(self, now: float | None = None) -> bool:
        if not self.enabled or not self.active or not self._timeout_armed:
            return False
        current = time.monotonic() if now is None else now
        return current - self.last_activity >= self.timeout_seconds

    def expire(self) -> None:
        self.active = False
        self.last_activity = 0.0
        self._timeout_armed = False
