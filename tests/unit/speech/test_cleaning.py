from __future__ import annotations

from app.speech.cleaning import clean_markdown_artifacts


def test_clean_removes_bold_and_italics():
    text = "1. **Sandisk Ultra Fit 2TB**: ótima opção, *portátil* e rápida."
    cleaned = clean_markdown_artifacts(text)
    assert cleaned == "1. Sandisk Ultra Fit 2TB: ótima opção, portátil e rápida."


def test_clean_keeps_plain_text_untouched():
    text = "olá ALPHA, tudo certo?"
    assert clean_markdown_artifacts(text) == text


def test_clean_removes_headings_and_code_blocks():
    text = "## Exemplo\n```python\nx = 1\n```\n`inline` fim."
    cleaned = clean_markdown_artifacts(text)
    assert "##" not in cleaned
    assert "```" not in cleaned
    assert "`" not in cleaned
    assert "inline" in cleaned


def test_clean_rewrites_links_and_bullets():
    text = "- [docs](https://example.com)\n- **item**"
    cleaned = clean_markdown_artifacts(text)
    assert "docs" in cleaned
    assert "]" not in cleaned
    assert "**" not in cleaned
