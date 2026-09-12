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
    """Gate determinístico barato antes da execução."""

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
        if len(words) >= 20 or any(term in normalized for term in self._COMPLEX_TERMS):
            return ComplexityDecision(Complexity.COMPLEX, True, True, "múltiplos passos ou ação externa detectados")
        if len(words) >= 9 or any(term in normalized for term in self._MEDIUM_TERMS):
            return ComplexityDecision(Complexity.MEDIUM, False, True, "ação que pode alterar estado ou exigir ferramenta")
        return ComplexityDecision(Complexity.SIMPLE, False, False, "interação curta e de baixo custo operacional")


_STRICT_TOOLS = frozenset({
    "browser_click", "browser_js", "browser_open", "browser_navigate",
    "open_app", "open_url", "open_file", "close_app", "move_app",
    "mouse_click", "mouse_scroll", "type_text", "press_key", "click_text",
    "run_shell", "run_code", "task_execute", "procedure_run", "macro_run",
})


class ReliableAgentCore(SerializedAgentCore):
    """Facade final: complexity gate, plano executável e verificação pós-ação."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.complexity_gate = ComplexityGate()
        self._complexity = ComplexityDecision(Complexity.SIMPLE, False, False, "sem tarefa ainda")
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
        plan = getattr(self, "_plan", None)
        if self._complexity.requires_plan and plan is None:
            self._emit(EventType.agent_progress, {"kind": "plan_missing", "message": "Tarefa complexa sem plano estruturado; usando fallback supervisionado."})
        elif plan is not None:
            try:
                plan.status = "running"
                plan.updated_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
            except Exception:
                pass
        return await super()._run_agent_loop(
            provider, messages, permissions, conversation_id, stream_tokens, task, context, expose_tools
        )

    def _initial_tool_names(self, task: str, permissions: set[Any]) -> set[str]:
        names = super()._initial_tool_names(task, permissions)
        plan = getattr(self, "_plan", None)
        if plan is None or not getattr(plan, "steps", None):
            return names
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
        if self._complexity.level is Complexity.SIMPLE:
            return await super()._provider_turn(provider, messages, tools, stream_tokens)
        guidance = LLMMessage(
            role="system",
            content=(
                "GATE DE EXECUÇÃO: classifique o estado antes de concluir. "
                f"complexidade={self._complexity.level.value}. "
                "Use tool calling nativo. Considere ações apenas EXECUTADAS até haver "
                "evidência de pós-condição. Não alegue conclusão sem evidência."
            ),
        )
        enriched = list(messages)
        enriched.insert(1 if enriched and enriched[0].role == "system" else 0, guidance)
        return await super()._provider_turn(provider, enriched, tools, stream_tokens)

    def _checkpoint_for(self, tool_name: str) -> Any | None:
        plan = getattr(self, "_plan", None)
        if plan is None:
            return None
        for step in plan.steps:
            if step.tool_hint == tool_name and step.status not in {"completed", "cancelled"}:
                return step
        return None

    def _update_plan_checkpoint(self, execution: ExecutionEvidence) -> None:
        tool_name = execution.tool.split("(", 1)[0]
        step = self._checkpoint_for(tool_name)
        if step is None:
            return
        step.attempts += 1
        if not execution.success:
            step.status = "failed"
            self._emit(EventType.task_failed, {"step_id": step.id, "tool": tool_name, "error": execution.error or "falha"})
            return
        if tool_name in _STRICT_TOOLS and not execution.verified:
            step.status = "running"
            self._emit(EventType.verification_started, {"step_id": step.id, "tool": tool_name, "expected": step.expected_evidence})
            return
        step.status = "completed"
        plan = getattr(self, "_plan", None)
        if plan is not None:
            pending = [item for item in plan.steps if item.status not in {"completed", "cancelled"}]
            if not pending:
                plan.status = "completed"
            else:
                plan.status = "running"
        self._emit(EventType.task_step_completed, {
            "step_id": step.id,
            "tool": tool_name,
            "attempts": step.attempts,
            "verified": execution.verified,
        })

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        permissions: set[Any],
        conversation_id: str | None,
        allowed_names: set[str],
    ) -> tuple[LLMMessage, ExecutionEvidence | None]:
        message, execution = await super()._execute_tool(tool_call, permissions, conversation_id, allowed_names)
        if execution is None or not execution.success:
            if execution is not None:
                self._update_plan_checkpoint(execution)
            return message, execution

        tool_name = execution.tool.split("(", 1)[0]
        if (
            not self._complexity.requires_verification
            or tool_name not in _STRICT_TOOLS
            or tool_name == "verify_screen"
            or execution.verified
        ):
            self._update_plan_checkpoint(execution)
            return message, execution

        verifier = self.tool_registry.get("verify_screen") if "verify_screen" in self.tool_registry.tools else None
        if verifier is None:
            self._update_plan_checkpoint(execution)
            return message, execution

        verify_goal = self._active_task or (getattr(getattr(self, "_plan", None), "expected_result", None) or tool_name)
        self._emit(EventType.verification_started, {"tool": tool_name, "goal": verify_goal})
        try:
            verify_result = await verifier.execute(goal=verify_goal, max_retries=0)
        except Exception as exc:
            execution.result = {**(execution.result if isinstance(execution.result, dict) else {}), "verification": {"achieved": None, "error": str(exc)}}
            execution.status = "executed_unverified"
            self._update_plan_checkpoint(execution)
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
        self._emit(EventType.verification_completed, {"tool": tool_name, "achieved": achieved, "verified": execution.verified})
        self._update_plan_checkpoint(execution)
        return message, execution

    def _apply_honesty_gate(self, content: str, evidence: list[ExecutionEvidence]) -> str:
        result = super()._apply_honesty_gate(content, evidence)
        unverified = [item for item in evidence if item.success and item.tool.split("(", 1)[0] in _STRICT_TOOLS and not item.verified]
        if unverified and result == content and self._complexity.requires_verification:
            self._emit(EventType.honesty_gate, {
                "claim": "unverified_strict_action",
                "tools": [item.tool for item in unverified],
                "executed": True,
                "verified": False,
            })
            return "A ação foi executada, mas não consegui confirmar a pós-condição. Não vou afirmar que ela foi concluída sem essa evidência."
        return result


__all__ = ["Complexity", "ComplexityDecision", "ComplexityGate", "ReliableAgentCore"]
