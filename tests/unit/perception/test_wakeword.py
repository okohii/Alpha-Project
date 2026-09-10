from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum


from app.perception.wakeword import find_wake_word, normalize, strip_wake_word

DEFAULT = "alpha"


def test_normalize_removes_accents_and_lowercases():
    assert normalize("Álpha, Járvis!") == "alpha, jarvis!"


def test_find_wake_word_matches_plain():
    assert find_wake_word("alpha, que horas são?", DEFAULT) == "alpha"


def test_find_wake_word_matches_uppercase():
    assert find_wake_word("ALPHA me liga", DEFAULT) == "alpha"


def test_find_wake_word_matches_accented():
    assert find_wake_word("álpha, acorda", DEFAULT) == "alpha"


def test_find_wake_word_rejects_embedded_substring():
    assert find_wake_word("alfafa no campo", DEFAULT) is None


def test_find_wake_word_multiple_aliases():
    assert find_wake_word("jarvis, responda", "alpha,jarvis") == "jarvis"


def test_find_wake_word_no_match_returns_none():
    assert find_wake_word("boa noite", DEFAULT) is None


def test_find_wake_word_empty_text():
    assert find_wake_word("", DEFAULT) is None


def test_strip_wake_word_returns_remainder():
    found, remainder = strip_wake_word("alpha, que horas são?", DEFAULT)
    assert found is True
    assert remainder == "que horas sao?"


def test_strip_wake_word_alone_returns_empty():
    found, remainder = strip_wake_word("alpha", DEFAULT)
    assert found is True
    assert remainder == ""


def test_strip_wake_word_missing_keeps_text():
    found, remainder = strip_wake_word("boa noite", DEFAULT)
    assert found is False
    assert remainder == "boa noite"


def test_strip_wake_word_inside_sentence():
    found, remainder = strip_wake_word("me chama alpha e responde", DEFAULT)
    assert found is True
    assert remainder == "me chama e responde"


def test_strip_wake_word_preserves_original_when_not_found():
    found, remainder = strip_wake_word("Comprar café", DEFAULT)
    assert found is False
    assert remainder == "Comprar café"
