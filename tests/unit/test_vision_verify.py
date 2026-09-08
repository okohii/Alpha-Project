from __future__ import annotations

import asyncio

from app.llm.vision_verify import (
    OllamaVisionVerifier,
    _parse_verdict,
    build_verify_prompt,
)


def test_build_prompt_includes_goal():
    prompt = build_verify_prompt("abrir o website do github")
    assert "abrir o website do github" in prompt
    assert "achieved" in prompt


def test_parse_verdict_handles_bare_json():
    raw = '{"achieved": true, "confidence": 0.9, "feedback": "github aberto"}'
    result = _parse_verdict(raw)
    assert result["achieved"] is True
    assert result["confidence"] == 0.9
    assert result["feedback"] == "github aberto"


def test_parse_verdict_handles_markdown_and_string_bool():
    raw = '```json\n{"achieved": "sim", "confidence": "0.7"}\n``` texto extra'
    result = _parse_verdict(raw)
    assert result["achieved"] is True
    assert result["confidence"] == 0.7


def test_parse_verdict_gracious_on_garbage():
    result = _parse_verdict("não, isso não é json de jeito nenhum")
    assert result["achieved"] is None
    assert result["confidence"] == 0.0


def test_parse_verdict_missing_json_object():
    result = _parse_verdict("sem chaves aqui")
    assert result["achieved"] is None


def test_unavailable_returns_inconclusive(monkeypatch):
    verifier = OllamaVisionVerifier(provider=None)
    assert verifier.available() is False

    async def fake_run():
        return await verifier.verify("/tmp/x.png", "meta")

    result = asyncio.run(fake_run())
    assert result["achieved"] is None
    assert "sem visão" in result["last"]["feedback"]


def test_unavailable_provider_false(monkeypatch):
    class Disabled:
        def available(self):
            return False

    verifier = OllamaVisionVerifier(provider=Disabled())
    assert verifier.available() is False


def test_verify_success_first_try(monkeypatch):
    class FakeProvider:
        def available(self):
            return True

        async def describe(self, image_path, prompt=None, max_chars=2000):
            return '{"achieved": true, "confidence": 1.0, "feedback": "ok"}'

    verifier = OllamaVisionVerifier(provider=FakeProvider())
    result = asyncio.run(verifier.verify("/tmp/a.png", "meta"))
    assert result["achieved"] is True
    assert result["attempts"] == 1


def test_verify_retries_until_success(monkeypatch):
    calls = {"n": 0}

    class FlakyProvider:
        def available(self):
            return True

        async def describe(self, image_path, prompt=None, max_chars=2000):
            calls["n"] += 1
            if calls["n"] < 3:
                return '{"achieved": false, "confidence": 0.4, "feedback": "ainda não"}'
            return '{"achieved": true, "confidence": 0.9, "feedback": "agora sim"}'

    verifier = OllamaVisionVerifier(provider=FlakyProvider())
    result = asyncio.run(verifier.verify("/tmp/a.png", "meta", max_retries=3, retry_delay=0))
    assert result["achieved"] is True
    assert result["attempts"] == 3
    assert len(result["details"]) == 3


def test_verify_gives_up_after_max_retries(monkeypatch):
    async def never(image_path, prompt=None, max_chars=2000):
        return '{"achieved": false, "confidence": 0.1, "feedback": "nada"}'

    class StickyProvider:
        def available(self):
            return True

        describe = staticmethod(never)

    verifier = OllamaVisionVerifier(provider=StickyProvider())
    result = asyncio.run(verifier.verify("/tmp/a.png", "meta", max_retries=2, retry_delay=0))
    assert result["achieved"] is False
    assert result["attempts"] == 3


def test_verify_propagates_vision_error(monkeypatch):
    class BrokenProvider:
        def available(self):
            return True

        async def describe(self, image_path, prompt=None, max_chars=2000):
            raise RuntimeError("ollama caiu")

    verifier = OllamaVisionVerifier(provider=BrokenProvider())
    result = asyncio.run(verifier.verify("/tmp/a.png", "meta", max_retries=0))
    assert result["achieved"] is None
    assert "erro de visão" in result["last"]["feedback"]