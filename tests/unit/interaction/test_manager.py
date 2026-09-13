from __future__ import annotations

from app.interaction import InteractionManager


def test_dormant_ignores_speech_until_wake_word():
    manager = InteractionManager(enabled=True, wake_words="alpha")
    decision = manager.decide("abre o chrome")
    assert decision.accepted is False
    assert decision.reason == "wake_word_missing"
    assert manager.state == "dormant"


def test_wake_word_activates_session_and_strips_word():
    manager = InteractionManager(enabled=True, wake_words="alpha")
    decision = manager.decide("ALPHA, abre o Chrome")
    assert decision.accepted is True
    assert decision.activated is True
    assert decision.command == "abre o Chrome"
    assert manager.state == "active"


def test_active_session_accepts_commands_without_wake_word():
    manager = InteractionManager(enabled=True, wake_words="alpha")
    manager.decide("alpha")
    decision = manager.decide("abre o navegador")
    assert decision.accepted is True
    assert decision.command == "abre o navegador"
    assert decision.activated is False


def test_close_command_is_not_confused_with_ending_interaction():
    manager = InteractionManager(enabled=True, wake_words="alpha")
    manager.decide("alpha")
    decision = manager.decide("fechar o chrome")
    assert decision.accepted is True
    assert decision.ended is False
    assert decision.command == "fechar o chrome"


def test_end_word_returns_to_dormant():
    manager = InteractionManager(enabled=True, wake_words="alpha")
    manager.decide("alpha")
    decision = manager.decide("encerrar")
    assert decision.accepted is False
    assert decision.ended is True
    assert manager.state == "dormant"


def test_timeout_expires_active_session():
    manager = InteractionManager(enabled=True, wake_words="alpha", timeout_seconds=25)
    manager.decide("alpha")
    # O timeout só é armado quando ALPHA termina de falar (touch_activity);
    # dormindo-até-resposta ele permanece armado pela atividade do turno.
    assert manager.expired(manager.last_activity + 25) is False
    manager.touch_activity()
    assert manager.expired(manager.last_activity + 25) is True
    manager.expire()
    assert manager.state == "dormant"


def test_disabled_wake_word_preserves_always_on_behavior():
    manager = InteractionManager(enabled=False, wake_words="alpha")
    decision = manager.decide("abre o chrome")
    assert decision.accepted is True
    assert decision.command == "abre o chrome"
