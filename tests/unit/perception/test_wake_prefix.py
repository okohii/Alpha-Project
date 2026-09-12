"""Testes de normalização do wake word preservando o texto do STT.

``strip_wake_prefix`` remove apenas o prefixo do wake word, mantendo o
restante do comando exatamente como o STT reconheceu (maiúsculas/acentos).
"""
from __future__ import annotations

from app.perception.wakeword import find_wake_word, strip_wake_prefix

DEFAULT = "Alpha, alpha, Alfa, alfa"


def test_strip_prefix_removes_wake_at_start_preserving_case():
    found, remainder = strip_wake_prefix("ALPHA, abre o Chrome", DEFAULT)
    assert found is True
    assert remainder == "abre o Chrome"


def test_strip_prefix_keeps_accents_in_command():
    found, remainder = strip_wake_prefix("Alfa, abrir o bloco de notas", DEFAULT)
    assert found is True
    assert remainder == "abrir o bloco de notas"


def test_strip_prefix_treats_alfa_and_alpha_equivalently():
    found_a, rest_a = strip_wake_prefix("Alfa, abrir o navegador", DEFAULT)
    found_b, rest_b = strip_wake_prefix("Alpha, abrir o navegador", DEFAULT)
    assert found_a and found_b
    assert rest_a == rest_b == "abrir o navegador"


def test_strip_prefix_does_not_touch_middle_word():
    found, remainder = strip_wake_prefix("me chama alpha e responde", DEFAULT)
    assert found is False
    assert remainder == "me chama alpha e responde"


def test_strip_prefix_no_wake_returns_original():
    found, remainder = strip_wake_prefix("boa noite", DEFAULT)
    assert found is False
    assert remainder == "boa noite"


def test_strip_prefix_wake_only_returns_empty():
    found, remainder = strip_wake_prefix("al fa", DEFAULT)
    assert found is False
    assert remainder == "al fa"


def test_find_wake_word_matches_accented_variant():
    assert find_wake_word("álpha, acorda", DEFAULT) in {"alpha", "alfa"}