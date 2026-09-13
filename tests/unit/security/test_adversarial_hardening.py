"""Testes adversariais de segurança (Parte 53).

Tentam os vetores de ataque principais e provam que a arquitetura os BLOQUEIA
estruturalmente — nenhum depende de prompt.
"""
from __future__ import annotations

import pytest

from app.security.capabilities import (
    NON_AUTO_APPROVABLE,
    Capability,
    capabilities_for,
    is_auto_approvable,
    risk_level_for_tool,
)
from app.security.permissions import SecurityLevel
from app.security.policy import risk_requires_confirmation
from app.security.redact import redact_secrets, redact_text
from app.tools.base import ToolPermission


def test_write_does_not_imply_execute():
    assert Capability.WRITE_FILE not in capabilities_for("run_code")
    assert Capability.EXECUTE not in capabilities_for("file_write")
    assert Capability.EXECUTE not in capabilities_for("memory_save")


def test_execution_never_auto_approvable():
    for tool in ("run_shell", "run_code", "browser_js", "macro_run", "task_execute"):
        assert is_auto_approvable(tool) is False, tool
        assert capabilities_for(tool) & NON_AUTO_APPROVABLE, tool


def test_write_file_is_never_auto_approvable():
    # C2: SYSTEM_CONTROL (escrita em disco) não pode ser auto-aprovada por flag.
    assert is_auto_approvable("file_write") is False
    assert is_auto_approvable("task_register_path") is False
    assert is_auto_approvable("move_app") is False


def test_system_control_never_auto_approvable():
    for tool in ("file_write", "task_register_path", "move_app", "open_app", "close_app"):
        assert is_auto_approvable(tool) is False, tool
        assert capabilities_for(tool) & NON_AUTO_APPROVABLE, tool


def test_risk_reclassified_for_real_nature():
    # Parte 21: ações disruptivas/rede não são "low write".
    for tool in ("close_app", "open_app", "open_file", "move_app"):
        assert risk_requires_confirmation(tool, ToolPermission.write) is True, tool
        assert risk_level_for_tool(tool) in (SecurityLevel.medium, SecurityLevel.high)


def test_run_code_shell_are_high_risk():
    assert risk_requires_confirmation("run_shell", ToolPermission.read) is True
    assert risk_requires_confirmation("run_code", ToolPermission.read) is True
    assert risk_requires_confirmation("browser_js", ToolPermission.write) is True


@pytest.mark.anyio
async def test_run_code_description_is_honest():
    from app.skills.shell.service import SandboxRunner
    from app.skills.shell.tools.execute import RunCodeTool

    tool = RunCodeTool(SandboxRunner())
    assert "isolad" not in tool.description.lower()
    assert "ARBITRÁRIO" in tool.description.upper() or "arbitrário" in tool.description


@pytest.mark.anyio
async def test_system_config_never_leaks_allowlist_or_urls():
    from app.skills.system.tools.config import SystemConfigTool

    result = await SystemConfigTool().execute()
    data = result.data
    assert "base_url" not in data
    assert "allowed_directories" not in data
    assert data["model"]


def test_redactor_removes_named_secrets():
    scrubbed = redact_secrets({"command": "echo x", "password": "senha123"})
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["command"] == "echo x"


def test_redactor_detects_embedded_secrets():
    assert "[REDACTED]" in redact_text("Authorization: Bearer abcdefghijklmn")
    assert "sk-1234567890abcdef" not in redact_text("key=sk-1234567890abcdef")
    assert "segredo" not in redact_text("x-api-key=segredo")
    assert "senha123" not in redact_text('{"password": "senha123"}')


def test_evidence_model_has_vision_and_inference():
    from app.evidence import Evidence, EvidenceKind

    assert EvidenceKind.VISION == "vision"
    assert EvidenceKind.ACCESSIBILITY_TREE == "accessibility_tree"
    assert EvidenceKind.INFERENCE == "inference"
    evidence = Evidence(kind=EvidenceKind.VISION, success=True, confidence=0.9)
    assert evidence.success is True


def test_ocr_perceptor_is_not_a_fake_capability():
    from app.perception.ocr import OCRPerceptor

    perceptor = OCRPerceptor()
    assert perceptor.available is False
    result = perceptor.perceive(image_path="/tmp/x.png")
    assert result.success is False
    assert result.result is None


# ---- Estratégia de retry estruturada (P9) ----

def test_failure_classifier_distinguishes_classes():
    from app.agent.agent import classify_failure

    assert classify_failure("excedeu o tempo máximo") == "timeout"
    assert classify_failure("Uso negado pelo usuário") == "permission"
    assert classify_failure("Aplicativo não encontrado: x") == "target_missing"
    assert classify_failure("Argumentos inválidos: obrigatório 'app' ausente") == "invalid_argument"
    assert classify_failure("Não foi possível falar com o Ollama") == "transient"
    assert classify_failure("") == "unknown"
    assert classify_failure("erro genérico de execução") == "environment"


def test_failed_tool_result_carries_retry_strategy():
    import json

    from app.agent.agent import RETRY_STRATEGY_HINT, AgentCore

    agent = object.__new__(AgentCore)
    msg = agent._tool_result_message(
        "open_app", success=False, response={}, error="excedeu o tempo máximo"
    )
    payload = json.loads(msg.content)
    assert payload["failure_class"] == "timeout"
    assert "NÃO repita a mesma chamada" in payload["retry_strategy"]
    assert payload["retry_strategy"] == RETRY_STRATEGY_HINT["timeout"]


# ---- Telemetria e planner (10/10) ----

def test_evidence_carries_session_and_conversation_ids():
    from app.llm.base import ExecutionEvidence

    evidence = ExecutionEvidence(
        action_id="a1",
        tool="open_app",
        arguments={},
        executed_at="now",
        success=True,
        result={},
        session_id="sess-abc",
        conversation_id="conv-1",
    )
    dumped = evidence.to_dict()
    assert dumped["session_id"] == "sess-abc"
    assert dumped["conversation_id"] == "conv-1"


@pytest.mark.anyio
async def test_agent_returns_session_id():
    from app.agent.agent import AgentCore
    from app.llm.base import LLMResponse
    from app.llm.mock import MockLLMProvider
    from app.llm.router import LLMRouter
    from app.tools.registry import ToolRegistry

    provider = MockLLMProvider([LLMResponse(content="ok")])
    agent = AgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=ToolRegistry(tools={}),
        memory_service=_FakeMem(),
    )
    result = await agent.chat("oi")
    assert result["session_id"]
    assert len(result["session_id"]) >= 8


class _FakeMem:
    async def search_memories(self, *a, **k):
        return []

    async def load_profile(self, *a, **k):
        return []

    async def save_episode(self, *a, **k):
        return None


def test_plan_checkpoint_records_failure_class():
    from app.agent.planner import Planner
    from app.agent.reliable import ReliableAgentCore
    from app.assistant.intent import Goal, Intent, Task
    from app.core.events import EventType
    from app.llm.base import ExecutionEvidence

    core = object.__new__(ReliableAgentCore)
    core._plan = Planner().build_plan(Goal(intent=Intent(name="gui_action"), tasks=[Task(tool_hint="mouse_click")]))
    events = []
    core._emit = lambda t, payload=None, duration_ms=None: events.append(t) if t is EventType.task_failed else None
    core._active_task = "tarefa"
    execution = ExecutionEvidence(
        action_id="a1", tool="mouse_click", arguments={}, executed_at="now",
        success=False, result={}, error="excedeu o tempo máximo",
    )
    core._update_plan_checkpoint(execution)
    assert events and events[-1] is EventType.task_failed
    assert core._plan.steps[0].status == "failed"
    assert getattr(core._plan.steps[0], "last_failure_class", "") == "timeout"