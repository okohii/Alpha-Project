"""Helpers de apresentação compartilhados entre Avatar e Overlay (Fase 5.5).

As duas sessões de UI duplicavam parsing de confirmação e serialização de
execução. Aqui ficam as partes idênticas; as máquinas de estado específicas
continuam em cada domínio.
"""
from __future__ import annotations

from app.security import SENSITIVE_PREFIX


def parse_confirmation_candidate(candidate: str) -> dict[str, str]:
    """Extrai tool + argumentos legíveis de um candidate de confirmação."""
    if candidate.startswith(SENSITIVE_PREFIX):
        rest = candidate[len(SENSITIVE_PREFIX) :]
        tool_name, sep, args = rest.partition(": ")
        return {
            "kind": "action",
            "tool": tool_name.strip() if sep else rest.strip(),
            "arguments": args.strip() if sep else "",
        }
    return {"kind": "path", "tool": "permissão de acesso", "arguments": candidate}


def confirmation_payload(candidate: str) -> dict[str, str]:
    """Payload de confirmação a enviar ao cliente da UI."""
    display = parse_confirmation_candidate(candidate)
    return {
        "type": "confirmation",
        "kind": display["kind"],
        "tool": display["tool"],
        "arguments": display["arguments"],
    }


__all__ = ["parse_confirmation_candidate", "confirmation_payload"]