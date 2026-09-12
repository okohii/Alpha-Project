"""Regressões para impedir respostas que confundem intenção com execução."""
from __future__ import annotations

from app.agent.agent import AgentCore


def test_failure_claim_is_not_success():
    assert AgentCore._claims_success("Não consegui abrir o navegador.") is False
    assert AgentCore._claims_success("Tentei enviar a mensagem, mas falhou.") is False


def test_success_claim_requires_real_execution_at_gate():
    # O detector só classifica a linguagem; a decisão final é feita pelo
    # _apply_honesty_gate, que exige evidência de ferramenta com sucesso.
    assert AgentCore._claims_success("Abri o navegador com sucesso.") is True


def test_memory_claim_is_not_success_when_negated():
    assert AgentCore._claims_memory_success("Não salvei isso na memória.") is False


def test_textual_tool_call_is_never_exposed_as_execution():
    content = '{"name":"open_app","arguments":{"app_name":"WhatsApp"}}'
    assert AgentCore._scrub_internal_json(content) != content
    assert "open_app" not in AgentCore._scrub_internal_json(content)


def test_embedded_tool_call_json_is_removed():
    content = 'Vou executar {"name":"open_url","arguments":{"url":"https://example.com"}} agora.'
    scrubbed = AgentCore._scrub_internal_json(content)
    assert "open_url" not in scrubbed
    assert "https://example.com" not in scrubbed
