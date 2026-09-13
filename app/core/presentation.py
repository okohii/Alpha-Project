"""Helpers de apresentação compartilhados entre Avatar e Overlay."""
from __future__ import annotations

from typing import Any

from app.core.events import EventType, SystemEvent
from app.security import SENSITIVE_PREFIX


_EXECUTION_LABELS = {
    EventType.tool_selected: "ferramenta selecionada",
    EventType.tool_started: "ferramenta executando",
    EventType.tool_finished: "ferramenta concluída",
    EventType.tool_failed: "ferramenta falhou",
    EventType.skill_started: "skill iniciada",
    EventType.skill_finished: "skill concluída",
    EventType.verification_started: "verificação iniciada",
    EventType.verification_completed: "verificação concluída",
    EventType.task_created: "tarefa criada",
    EventType.task_step_completed: "passo concluído",
    EventType.task_completed: "tarefa concluída",
    EventType.task_failed: "tarefa falhou",
    EventType.honesty_gate: "controle de evidência",
    EventType.textual_tool_call_blocked: "tool call textual bloqueada",
}


def parse_confirmation_candidate(candidate: str) -> dict[str, str]:
    """Extrai tool + argumentos legíveis de um candidate de confirmação."""
    if candidate.startswith(SENSITIVE_PREFIX):
        rest = candidate[len(SENSITIVE_PREFIX) :]
        tool_name, sep, args = rest.partition(": ")
        return {"kind": "action", "tool": tool_name.strip() if sep else rest.strip(), "arguments": args.strip() if sep else ""}
    return {"kind": "path", "tool": "permissão de acesso", "arguments": candidate}


def confirmation_payload(candidate: str) -> dict[str, str]:
    display = parse_confirmation_candidate(candidate)
    return {"type": "confirmation", **display}


def execution_payload(event: SystemEvent) -> dict[str, Any]:
    """Normaliza eventos de execução para qualquer UI sem duplicar regras."""
    payload = dict(event.payload or {})
    target = payload.get("tool") or payload.get("skill") or payload.get("task_id") or ""
    return {
        "type": "execution",
        "event": event.type.value,
        "label": _EXECUTION_LABELS.get(event.type, event.type.value),
        "target": str(target),
        "success": payload.get("success"),
        "duration_ms": event.duration_ms,
        "detail": payload.get("error") or payload.get("message") or payload.get("preview") or "",
    }


__all__ = ["parse_confirmation_candidate", "confirmation_payload", "execution_payload"]
