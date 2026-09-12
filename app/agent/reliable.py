from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.agent.serialized import SerializedAgentCore
from app.core.events import EventType
from app.llm.base import ExecutionEvidence, LLMMessage, LLMProvider, LLMResponse, ToolCall


class Complexity(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


@dataclass(frozen=True, slots=True)
class ComplexityDecision:
    level: Complexity
    requires_plan: bool
    requires_verification: bool
    reason: str


class ComplexityGate:
    """Gate determinístico barato antes da execução.

    Não faz outra chamada ao LLM. A classificação serve para selecionar a
    profundidade operacional: simples segue rápido; médio exige contexto de
    execução; complexo exige plano + verificação.
    """

    _COMPLEX_TERMS = (
        "depois", "em seguida", "primeiro", "segundo passo", "vários passos",
        "whatsapp", "telegram", "discord", "email", "github", "gitlab",
        "copiar", "colar", "enviar", "mandar", "clicar", "digitar", "mover",
        "renomear", "editar", "criar arquivo", "abrir navegador", "navegador",
        "compare", "analisar", "investigar", "organizar", "automatizar",
    )
    _MEDIUM_TERMS = (
        "abrir", "fechar", "pesquisar", "procurar", "criar", "salvar",
        "lembrar", "agendar", "arquivo", "pasta", "documento", "macro",
    )

    def classify(self, text: str) -> ComplexityDecision:
        normalized = (text or "").strip().lower()
        words = normalized.split()
        complex_hit = any(term in normalized for term in self._COMPLEX_TERMS)
        if len(words) >= 20 or complex_hit:
            return ComplexityDecision(
                Complexity.COMPLEX,
                requires_plan=True,
                requires_verification=True,
                reason="múltiplos passos ou ação externa detectados",
            )
        medium_hit = any(term in normalized for term in self._MEDIUM_TERMS)
        if len(words) >= 9 or medium_hit:
            return ComplexityDecision(
                Complexity.MEDIUM,
                requires_plan=False,
                requires_verification=True,
                reason="ação que pode alterar estado ou exigir ferramenta",
            )
        return ComplexityDecision(
            Complexity.SIMPLE,
            requires_plan=False,
            requires_verification=False,
            reason="interação curta e de baixo custo operacional",
        )


_STRICT_TOOLS = frozenset({
    "browser_click", "browser_js", "browser_open", "browser_navigate",
    "open_app", "open_url", "open_file", "close_app", "move_app",
    "mouse_click", "mouse_scroll", "type_text", "press_key", "click_text",
    "run_shell", "run_code", "task_execute", "procedure_run", "macro_run",
})


class ReliableAgentCore(SerializedAgentCore):
    """Facade final do agente: plano, complexity gate e verificação pós-ação."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.complexity_gate = ComplexityGate()
        self._complexity = ComplexityDecision(
            Complexity.SIMPLE, False, False, "sem tarefa ainda"
        )
        self._active_task = ""

    async def _run_agent_loop(
        self,
        provider: LLMProvider,
        messages: list[LLMMessage],
        permissions: set[Any],
        conversation_id: str | None = None,
        stream_tokens: bool = False,
        task: str = "",
        context: Any | None = None,
        expose_tools: bool = True,
    ) -> tuple[LLMResponse, list[LLMMessage]]:
        self._active_task = task
        self._complexity = self.complexity_gate.classify(task)
        self._emit(EventType.agent_progress, {
            "kind": "complexity_gate",
            "level": self._complexity.level.value,
            "requires_plan": self._complexity.requires_plan,
            "requires_verification": self._complexity.requires_verification,
            "reason": self._complexity.reason,
        })
        return await super()._run_agent_loop(
            provider,
            messages,
            permissions,
            conversation_id,
            stream_tokens,
            task,
            context,
            expose_tools,
        )

    def _initial_tool_names(self, task: str, permissions: set[Any]) -> set[str]:
        names = super()._initial_tool_names(task, permissions)
        plan = getattr(self, "_plan", None)
        if plan is None or not getattr(plan, "steps", None):
            return names

        # O plano limita o primeiro conjunto exposto às tools necessárias aos
        # passos planejados; ferramentas auxiliares de observação permanecem.
        planned = {
            step.tool_hint
            for step in plan.steps
            if getattr(step, "status", "pending") not in {"completed", "cancelled"}
        }
        if planned:
            narrowed = names & planned
            if narrowed:
                return narrowed | ({"time", "system_info", "memory_search"} & names)
        return names

    async def _provider_turn(
        self,
        provider: LLMProvider,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        stream_tokens: bool,
    ) -> LLMResponse:
        decision = self._complexity
        if decision.level is Complexity.SIMPLE:
            return await super()._provider_turn(provider, messages, tools, stream_tokens)

        guidance = LLMMessage(
            role="system",
            content=(
                "GATE DE EXECUÇÃO: classifique o estado atual antes de concluir. "
                f"complexidade={decision.level.value}. "
                "Para cada ação, use ferramenta nativa quando disponível. "
                "Considere uma ação apenas EXECUTADA até existir evidência de pós-condição. "
                "Não alegue conclusão sem evidência."
            ),
        )
        enriched = list(messages)
        enriched.insert(1 if enriched and enriched[0].role == "system" else 0, guidance)
        return await super()._provider_turn(provider, enriched, tools, stream_tokens)

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        permissions: set[Any],
        conversation_id: str | None,
        allowed_names: set[str],
    ) -> tuple[LLMMessage, ExecutionEvidence | None]:
        message, execution = await super()._execute_tool(
            tool_call, permissions, conversation_id, allowed_names
        )
        if execution is None or not execution.success:
            return message, execution
        tool_name = execution.tool.split("(", 1)[0]
        if (
            not self._complexity.requires_verification
            or tool_name not in _STRICT_TOOLS
            or tool_name == "verify_screen"
            or execution.verified
        ):
            return message, execution

        verifier = self.tool_registry.get("verify_screen") if "verify_screen" in self.tool_registry.tools else None
        if verifier is None:
            execution.status = "executed_unverified"
            return message, execution

        verify_goal = self._active_task or (
            getattr(getattr(self, "_plan", None), "expected_result", None) or tool_name
        )
        try:
            verify_result = await verifier.execute(goal=verify_goal, max_retries=0)
        except Exception as exc:
            execution.result = {
                **(execution.result if isinstance(execution.result, dict) else {}),
                "verification": {"achieved": None, "error": str(exc)},
            }
            execution.status = "executed_unverified"
            return message, execution

        data = verify_result.data if isinstance(verify_result.data, dict) else {}
        achieved = data.get("achieved") is True
        execution.result = {
            **(execution.result if isinstance(execution.result, dict) else {}),
            "verification": {
                "achieved": data.get("achieved"),
                "confidence": data.get("confidence"),
                "feedback": data.get("feedback") or data.get("details"),
            },
        }
        execution.verified = bool(verify_result.success and achieved)
        execution.status = "verified" if execution.verified else "executed_unverified"
        self._emit(
            EventType.verification_completed,
            {
                "tool": tool_name,
                "achieved": achieved,
                "verified": execution.verified,
            },
        )
        return message, execution

    def _apply_honesty_gate(
        self,
        content: str,
        evidence: list[ExecutionEvidence],
    ) -> str:
        result = super()._apply_honesty_gate(content, evidence)
        unverified = [
            item for item in evidence
            if item.success and item.tool.split("(", 1)[0] in _STRICT_TOOLS and not item.verified
        ]
        if unverified and result == content and self._complexity.requires_verification:
            self._emit(EventType.honesty_gate, {
                "claim": "unverified_strict_action",
                "tools": [item.tool for item in unverified],
                "executed": True,
                "verified": False,
            })
            return (
                "A ação foi executada, mas não consegui confirmar a pós-condição. "
                "Não vou afirmar que ela foi concluída sem essa evidência."
            )
        return result


__all__ = ["Complexity", "ComplexityDecision", "ComplexityGate", "ReliableAgentCore"]
