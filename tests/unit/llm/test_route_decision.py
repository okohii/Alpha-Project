"""Testes da resolução observável de rota do LLM.

Garante que ``configured_mode``/``effective_mode``/``selected_route``/
``fallback_reason`` sejam sempre explícitos e que ``route=cloud`` jamais
apareça sem uma razão (``mode_cloud`` ou ``complex_task``), nem sem fallback
explícito quando o provedor primário falhar.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.llm.base import LLMResponse
from app.llm.router import FaultTolerantProvider, LLMRouter


class FakeProvider:
    model = "fake-model"

    def __init__(self, label: str, fail: bool = False) -> None:
        self.label = label
        self.fail = fail
        self.calls: list[dict] = []

    async def complete(self, messages, tools=None, temperature=0.2):
        self.calls.append({"messages": messages, "tools": tools})
        if self.fail:
            raise RuntimeError(f"{self.label} indisponível")
        return LLMResponse(content=f"resposta-{self.label}")


def _router(local=None, cloud=None) -> LLMRouter:
    return LLMRouter(
        local_provider=local or FakeProvider("local"),
        cloud_provider=cloud or FakeProvider("cloud"),
    )


# ---- modo local (default histórico) ----

def test_local_mode_routes_local():
    local = FakeProvider("local")
    router = _router(local=local)
    router.settings.llm_mode = "local"
    with patch.object(router, "_cloud_available", return_value=False):
        decision = router.resolve_route("abrir o bloco de notas")

    assert decision.configured_mode == "local"
    assert decision.effective_mode == "local"
    assert decision.selected_route == "local"
    assert decision.provider is local
    assert decision.fallback_reason == "mode_local"
    assert router.route_name() == "local"


def test_local_mode_keeps_cloud_as_explicit_fallback():
    local = FakeProvider("local")
    cloud = FakeProvider("cloud")
    router = _router(local=local, cloud=cloud)
    router.settings.llm_mode = "local"
    with patch.object(router, "_cloud_available", return_value=True):
        decision = router.resolve_route("abrir o bloco de notas")

    assert decision.selected_route == "local"
    assert decision.effective_mode == "local"
    assert decision.fallback_model == "fake-model"
    assert isinstance(decision.provider, FaultTolerantProvider)
    assert decision.provider.label == "local"
    assert decision.provider.fallback_label == "cloud"
    assert router.route_name() == "local"


# ---- modo cloud ----

def test_cloud_mode_routes_cloud_only_when_available():
    router = _router()
    router.settings.llm_mode = "cloud"
    with patch.object(router, "_cloud_available", return_value=True):
        decision = router.resolve_route("qualquer coisa")

    assert decision.configured_mode == "cloud"
    assert decision.effective_mode == "cloud"
    assert decision.selected_route == "cloud"
    assert decision.fallback_reason is None
    assert isinstance(decision.provider, FaultTolerantProvider)
    assert decision.provider.label == "cloud"


def test_cloud_mode_unavailable_routes_local_with_explicit_reason():
    local = FakeProvider("local")
    router = _router(local=local)
    router.settings.llm_mode = "cloud"
    with patch.object(router, "_cloud_available", return_value=False):
        decision = router.resolve_route("qualquer coisa")

    assert decision.effective_mode == "local"
    assert decision.selected_route == "local"
    assert decision.fallback_reason == "cloud_unavailable"
    assert decision.provider is local


# ---- fallback efetivo ----

@pytest.mark.anyio
async def test_local_failure_falls_back_to_cloud_with_reason():
    local = FakeProvider("local", fail=True)
    cloud = FakeProvider("cloud")
    provider = FaultTolerantProvider(
        primary=local, fallback=cloud, label="local", fallback_label="cloud", reason="mode_local"
    )

    response = await provider.complete([SimpleNamespace(role="user", content="oi")])

    assert response.content == "resposta-cloud"
    assert provider.last_route == "cloud"
    assert provider.last_fallback_reason == "local_unavailable"
    assert local.calls and cloud.calls


@pytest.mark.anyio
async def test_cloud_failure_falls_back_to_local_with_reason():
    local = FakeProvider("local")
    cloud = FakeProvider("cloud", fail=True)
    provider = FaultTolerantProvider(
        primary=cloud, fallback=local, label="cloud", fallback_label="local", reason="mode_cloud"
    )

    response = await provider.complete([SimpleNamespace(role="user", content="oi")])

    assert response.content == "resposta-local"
    assert provider.last_route == "local"
    assert provider.last_fallback_reason == "cloud_unavailable"


@pytest.mark.anyio
async def test_cloud_fallback_to_local_is_skipped_when_ollama_down(monkeypatch):
    async def _ollama_down(_url) -> bool:
        return False

    local = FakeProvider("local")
    local.base_url = "http://localhost:11434"
    cloud = FakeProvider("cloud", fail=True)
    provider = FaultTolerantProvider(
        primary=cloud, fallback=local, label="cloud", fallback_label="local"
    )

    monkeypatch.setattr("app.llm.router.ollama_available", _ollama_down)
    with pytest.raises(RuntimeError):
        await provider.complete([SimpleNamespace(role="user", content="oi")])

    # Fallback NO LLAMA: o erro da rota primária é preservado e a rota final
    # permanece cloud (nunca "morre" silenciosamente num fallback morto).
    assert provider.last_route == "cloud"
    assert provider.last_fallback_reason == "local_unavailable_ollama_down"
    assert local.calls == []


@pytest.mark.anyio
async def test_cloud_fallback_to_local_uses_ollama_when_available(monkeypatch):
    async def _ollama_up(_url) -> bool:
        return True

    local = FakeProvider("local")
    local.base_url = "http://localhost:11434"
    cloud = FakeProvider("cloud", fail=True)
    provider = FaultTolerantProvider(
        primary=cloud, fallback=local, label="cloud", fallback_label="local"
    )

    monkeypatch.setattr("app.llm.router.ollama_available", _ollama_up)
    response = await provider.complete([SimpleNamespace(role="user", content="oi")])

    assert response.content == "resposta-local"
    assert provider.last_route == "local"
    assert provider.last_fallback_reason == "cloud_unavailable"


@pytest.mark.anyio
async def test_no_tool_call_on_cloud_retries_local_once():
    """A rota exibe label 'cloud' -> o retry local da camada reliable é possível."""
    local = FakeProvider("local")
    cloud = FakeProvider("cloud")
    provider = FaultTolerantProvider(
        primary=cloud, fallback=local, label="cloud", fallback_label="local"
    )
    assert provider.route == "cloud"
    assert provider.local is local
    assert provider.cloud is cloud


# ---- observabilidade em describe_current ----

def test_describe_current_exposes_resolution():
    router = _router()
    router.settings.llm_mode = "local"
    with patch.object(router, "_cloud_available", return_value=False):
        payload = router.describe_current()

    assert payload["configured_mode"] == "local"
    assert payload["effective_mode"] == "local"
    assert payload["selected_route"] == "local"
    assert "fallback_reason" in payload


# ---- streaming tolerante a falhas (Fase 4.3) ----

class _StreamingProvider(FakeProvider):
    async def stream_turn(self, messages, tools=None, temperature=0.2):
        from app.llm.base import StreamedResponse

        streamed = StreamedResponse()

        async def _gen():
            for token in (f"{self.label}-token-", "1", "2", "3"):
                yield token

        streamed.generator = _gen()
        return streamed


class _FailingStreamingProvider(FakeProvider):
    async def stream_turn(self, messages, tools=None, temperature=0.2):
        from app.llm.base import StreamedResponse

        streamed = StreamedResponse()

        async def _gen():
            raise RuntimeError("stream indisponível")
            yield ""  # pragma: no cover

        streamed.generator = _gen()
        return streamed


@pytest.mark.anyio
async def test_ftp_streams_from_primary():
    local = _StreamingProvider("local")
    provider = FaultTolerantProvider(primary=local, label="local")
    assert provider.supports_streaming is True

    streamed = await provider.stream_turn([SimpleNamespace(role="user", content="oi")])
    tokens = [token async for token in streamed]
    assert tokens == ["local-token-", "1", "2", "3"]
    assert provider.last_route == "local"


@pytest.mark.anyio
async def test_ftp_streams_fallback_when_primary_fails_before_emitting():
    failing = _FailingStreamingProvider("cloud")
    local = FakeProvider("local")
    provider = FaultTolerantProvider(
        primary=failing, fallback=local, label="cloud", fallback_label="local"
    )

    streamed = await provider.stream_turn([SimpleNamespace(role="user", content="oi")])
    tokens = [token async for token in streamed]
    assert "resposta-local" in "".join(tokens)
    assert provider.last_route == "local"
    assert provider.last_fallback_reason == "cloud_unavailable"


@pytest.mark.anyio
async def test_ftp_without_primary_streaming_degrades_to_complete():
    plain = FakeProvider("local")
    provider = FaultTolerantProvider(primary=plain, label="local")
    assert provider.supports_streaming is False

    response = await provider.stream_turn([SimpleNamespace(role="user", content="oi")])
    assert response.content == "resposta-local"