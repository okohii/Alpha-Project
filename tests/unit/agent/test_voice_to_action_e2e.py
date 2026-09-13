"""Teste end-to-end (mocks) de Voz -> Task -> Skill -> Tool -> Verificação.

Caminho completo para "abrir o bloco de notas":

    task → Computer skill → open_app → resultado → verify_screen →
    execution completed + verified → resposta final

NUNCA pode produzir "não entendi" quando a tool está disponível e a execução
é bem-sucedida e verificada.
"""
from __future__ import annotations


async def _approve(candidate):
    return True


async def _deny(candidate):
    return False


import pytest

from app.agent.reliable import ReliableAgentCore
from app.assistant.facilitator import AssistantFacilitator
from app.llm.base import LLMResponse, ToolCall
from app.llm.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.skills.base import Skill
from app.skills.registry import SkillRegistry
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.registry import ToolRegistry


class FakeMemoryService:
    async def search_memories(self, query: str, limit: int = 5):
        return []

    async def load_profile(self, limit: int = 50):
        return []

    async def save_episode(self, user_message, response, tool_names=None):
        return None


class OpenAppTool(Tool):
    name = "open_app"
    description = "abre um aplicativo pelo nome"
    permission = ToolPermission.write

    def __init__(self):
        self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(
            name=self.name,
            success=True,
            data={"app": kwargs.get("app", ""), "launched": True},
        )

    def parameters_schema(self):
        return {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]}


class VerifyScreenTool(Tool):
    name = "verify_screen"
    description = "verifica se a meta foi alcançada na tela"
    permission = ToolPermission.read

    def __init__(self, achieved: bool = True):
        self.achieved = achieved
        self.calls = 0

    async def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(
            name=self.name,
            success=True,
            data={"achieved": self.achieved, "confidence": 0.9 if self.achieved else 0.1},
        )

    def parameters_schema(self):
        return {"type": "object", "properties": {"goal": {"type": "string"}}}


def _build_agent(*, verify_achieved: bool = True, llm_responses=None):
    open_app = OpenAppTool()
    verify = VerifyScreenTool(achieved=verify_achieved)
    tools = ToolRegistry(tools={"open_app": open_app, "verify_screen": verify, "time": _TimeTool()})

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="Computer",
            description="automação do computador",
            keywords=["bloco de notas", "notepad", "aplicativo"],
            tools=["open_app", "verify_screen"],
        )
    )
    registry.register(
        Skill(name="System", description="sistema", keywords=["hora"], tools=["time"])
    )

    provider = MockLLMProvider(
        llm_responses
        or [
            LLMResponse(
                content="",
                tool_calls=[ToolCall(name="open_app", arguments={"app": "bloco de notas"})],
            ),
            LLMResponse(content="Abri o bloco de notas."),
        ]
    )
    agent = ReliableAgentCore(
        llm_router=LLMRouter(local_provider=provider, cloud_provider=provider),
        tool_registry=tools,
        memory_service=FakeMemoryService(),
        skill_registry=registry,
        facilitator=AssistantFacilitator(skill_registry=registry),
        permission_request_handler=_approve,
    )
    agent.settings.agent_require_tool_verification = True
    return agent, open_app, verify


class _TimeTool(Tool):
    name = "time"
    description = "hora"
    permission = ToolPermission.read

    async def execute(self, **kwargs):
        return ToolResult(name=self.name, success=True, data={"utc": "2026-09-12T00:00:00Z"})

    def parameters_schema(self):
        return {"type": "object", "properties": {}}


@pytest.mark.anyio
async def test_e2e_abrir_bloco_de_notas_executed_and_verified():
    agent, open_app, verify = _build_agent()

    result = await agent.chat("abrir o bloco de notas")

    assert open_app.calls == 1
    assert verify.calls == 1
    assert "não entendi" not in result["response"]
    assert result["response"] == "Abri o bloco de notas."

    # Evidência observada: EXECUTADO + VERIFICADO (não INFERIDO).
    evidence = {item["tool"]: item for item in result["evidence"]}
    assert evidence["open_app"]["success"] is True
    assert evidence["open_app"]["verified"] is True
    assert evidence["open_app"]["status"] == "verified"

    assert "open_app" in result["tools_used"]
    assert result["tool_selection_status"] == "selected"
    assert result["selected_skills"] == ["Computer"]
    assert result["route"]["selected_route"] == "local"
    assert result["execution_id"].startswith("exec-")

    # Skill correta: apenas Computer + System(desejado) expostas; sem browser/files/web.
    assert "open_app" in result["exposed_tools"]
    assert {"browser_open", "web_search", "file_write"} & set(result["exposed_tools"]) == set()


@pytest.mark.anyio
async def test_e2e_execution_without_verification_never_claims_success():
    agent, open_app, verify = _build_agent(verify_achieved=False)

    result = await agent.chat("abrir o bloco de notas")

    assert open_app.calls == 1
    assert "não consegui verificar" in result["response"].lower() or (
        "confirmar" in result["response"].lower()
    )
    # Uma afirmação falsa de sucesso jamais passa.
    assert result["response"] != "Abri o bloco de notas."

    evidence = {item["tool"]: item for item in result["evidence"]}
    assert evidence["open_app"]["success"] is True
    assert evidence["open_app"]["verified"] is False
    assert evidence["open_app"]["status"] == "executed_unverified"


@pytest.mark.anyio
async def test_e2e_task_never_executes_twice_for_same_request():
    agent, open_app, _ = _build_agent()

    await agent.chat("abrir o bloco de notas")

    assert open_app.calls == 1