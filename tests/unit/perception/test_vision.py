from __future__ import annotations

import asyncio

import pytest

from app.perception.vision import OllamaVisionError, OllamaVisionProvider


class _FakeSettings:
    def __init__(self, vision_model):
        self.ollama_base_url = "http://ollama:11434"
        self.ollama_model = ""
        self.ollama_vision_model = vision_model
        self.llm_timeout_seconds = 60.0


def test_provider_not_available_without_model(monkeypatch, tmp_path):
    monkeypatch.setattr("app.perception.vision.vision.get_settings", lambda: _FakeSettings(""))
    provider = OllamaVisionProvider()
    assert provider.available() is False


def test_describe_requires_model(monkeypatch):
    monkeypatch.setattr("app.perception.vision.vision.get_settings", lambda: _FakeSettings(""))
    provider = OllamaVisionProvider()
    with pytest.raises(OllamaVisionError):
        asyncio.run(provider.describe("qualquer.png"))


def test_describe_sends_image_and_returns_text(monkeypatch, tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-png-bytes")
    monkeypatch.setattr(
        "app.perception.vision.vision.get_settings", lambda: _FakeSettings("gemma3:4b")
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, json):
            captured["url"] = url
            captured["payload"] = json

            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"message": {"content": "Botão Enviar: (560, 340)"}}

            return R()

    captured = {}
    monkeypatch.setattr("app.perception.vision.vision.httpx.AsyncClient", FakeClient)

    provider = OllamaVisionProvider(model="gemma3:4b")
    description = asyncio.run(provider.describe(str(image)))
    assert description == "Botão Enviar: (560, 340)"
    assert captured["url"] == "/api/chat"
    message = captured["payload"]["messages"][0]
    assert message["images"]
    import base64

    assert base64.b64decode(message["images"][0]) == b"fake-png-bytes"