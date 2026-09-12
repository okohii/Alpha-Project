"""Normalização textual na origem da saída de voz (#29)."""
from __future__ import annotations

from app.speech.cleaning import clean_for_voice


def test_common_typo_qe_is_fixed():
    assert clean_for_voice("não entendi bem o qe fazer") == "não entendi bem o que fazer"


def test_never_removes_legit_letters():
    # Regressão: selectores de variação com escape malformado removiam
    # as letras 'u', 'E', 'D' e dígitos de TODO o texto de voz.
    assert "Conseguimos" in clean_for_voice("**Conseguimos** resolver tudo.")
    assert clean_for_voice("tudo") == "tudo"


def test_emotion_tag_is_stripped_before_voice():
    assert "[happy]" not in clean_for_voice("[happy] Boa! Conseguimos resolver tudo.")
    assert clean_for_voice("[calm] Está tudo certo.") == "Está tudo certo."


def test_unrelated_braces_are_kept():
    assert "conteúdo" in clean_for_voice("um [conteúdo] entre colchetes")