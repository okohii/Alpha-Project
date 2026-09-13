"""Boundary do TTS e detecção de emoção explícita.

Garante que:
- apenas a resposta final do usuário chega ao pipeline de síntese (nenhum
  JSON/tool_call/debug interno);
- emoção explícita ("tom triste", "fale feliz") é detectada com source=explicit;
- "não fique triste" NÃO é pedido explícito de tristeza;
- emoção não vaza entre turnos.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.llm.base import LLMMessage, ToolCall
from app.llm.ollama import _serialize_message, parse_tool_calls
from app.speech.emotion import Emotion, detect_explicit_emotion
from app.speech.pipeline import VoicePipeline, _is_internal_content


class CaptureTTS:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    async def synthesize(self, text: str, delivery=None):
        if not text or not text.strip():
            return Path("/tmp/empty.wav")
        self.calls.append((text, delivery))
        return Path("/tmp/out.wav")


class FakeListener:
    async def start(self):
        ...

    async def stop(self):
        ...


class FakeSTT:
    async def transcribe(self, path):
        return type("T", (), {"text": "ola", "language": "pt", "segments": []})()


def _pipeline(tts: CaptureTTS) -> VoicePipeline:
    return VoicePipeline(listener=FakeListener(), stt=FakeSTT(), tts=tts)


# ---------------------------------------------------------------------------
# TTS boundary: só conteúdo final limpo fala
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tts_blocks_tool_call_json_payload():
    tool_call = {"name": "browser_open", "arguments": {"url": "https://web.whatsapp.com"}}
    pipeline = _pipeline(CaptureTTS())

    result = await pipeline.speak_expressive(json.dumps(tool_call, ensure_ascii=False))

    assert result["status"] == "text_only"
    assert "bloqueado" in result["detail"]


@pytest.mark.anyio
async def test_tts_blocks_tool_calls_list_payload():
    payload = {"tool_calls": [{"function": {"name": "x", "arguments": {}}}]}
    result = await _pipeline(CaptureTTS()).speak_expressive(
        json.dumps(payload, ensure_ascii=False)
    )
    assert result["status"] == "text_only"


@pytest.mark.anyio
async def test_tts_blocks_raw_execution_context():
    internal = {
        "execution_id": "exec-abc",
        "tool_calls": ["open_app"],
        "evidence_count": 3,
    }
    assert _is_internal_content(json.dumps(internal)) is True


@pytest.mark.anyio
async def test_tts_accepts_clean_final_response():
    tts = CaptureTTS()
    result = await _pipeline(tts).speak_expressive("Abri o WhatsApp com sucesso.")
    assert result["status"] == "ok"
    assert "WhatsApp" in tts.calls[-1][0]


def test_is_internal_content_rejects_normal_text():
    assert _is_internal_content("Boa noite! Como posso ajudar?") is False
    assert _is_internal_content("") is False
    assert _is_internal_content("O resultado foi 42.") is False


# ---------------------------------------------------------------------------
# Emoção explícita
# ---------------------------------------------------------------------------


def test_explicit_triste_tom_sad_high_confidence():
    state = detect_explicit_emotion("Agora eu quero um tom bem triste.")
    assert state is not None
    assert state.emotion == Emotion.sad
    assert state.source == "explicit"
    assert state.confidence == 1.0
    assert state.intensity >= 0.8


def test_explicit_fale_feliz_happy():
    state = detect_explicit_emotion("fale feliz")
    assert state is not None
    assert state.emotion == Emotion.happy
    assert state.source == "explicit"


def test_explicit_agora_fale_triste_sad():
    state = detect_explicit_emotion("agora fale triste")
    assert state is not None
    assert state.emotion == Emotion.sad
    assert state.source == "explicit"


def test_nao_fique_triste_is_not_explicit_sad():
    assert detect_explicit_emotion("não fique triste") is None


def test_nao_fale_triste_is_not_explicit_sad():
    assert detect_explicit_emotion("não fale triste") is None


def test_explicit_emotion_does_not_leak_between_requests():
    first = detect_explicit_emotion("fale feliz")
    second = detect_explicit_emotion("fale triste")
    clean = detect_explicit_emotion("qual é a capital do brasil?")
    assert first.emotion == Emotion.happy
    assert second.emotion == Emotion.sad
    assert clean is None


# ---------------------------------------------------------------------------
# Protocolo Ollama: assistant(tool_calls) é preservado
# ---------------------------------------------------------------------------


def test_ollama_serialize_assistant_preserves_tool_calls():
    message = LLMMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(name="browser_open", arguments={"url": "https://x.com"})],
    )
    payload = _serialize_message(message)
    assert payload["role"] == "assistant"
    assert payload["tool_calls"][0]["function"]["name"] == "browser_open"
    assert payload["tool_calls"][0]["function"]["arguments"] == {"url": "https://x.com"}


def test_ollama_parse_tool_calls_normalizes_string_arguments():
    calls = parse_tool_calls(
        [{"function": {"name": "open_app", "arguments": '{"app": "whatsapp"}'}}]
    )
    assert calls[0].name == "open_app"
    assert calls[0].arguments == {"app": "whatsapp"}


def test_ollama_tool_message_is_rendered_not_json_text():
    message = LLMMessage(
        role="tool",
        content=json.dumps(
            {"type": "function_response", "name": "time", "success": True, "response": {}}
        ),
    )
    payload = _serialize_message(message)
    assert payload["role"] == "tool"
    assert "[resultado da ferramenta:" in payload["content"]
    assert "{" not in payload["content"]