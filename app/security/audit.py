from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.security.policy import ToolAction
from app.tools.base import ToolPermission


@dataclass(slots=True)
class SecurityDecision:
    """Registro de decisão de segurança de uma chamada de tool.

    É a trilha de auditoria do modelo de least privilege: o que a ferramenta
    é (ação), o que ela queria (permissão), o que o turno concedeu, se exigiu
    confirmação da interface, qual foi a decisão e qual o resultado.
    """

    action: ToolAction
    tool: str
    permission_needed: ToolPermission | None
    access_granted: list[str]
    confirmation_required: bool
    decision: str
    reason: str
    result: str = "pending"
    arguments: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["permission_needed"] = (
            self.permission_needed.value if self.permission_needed else None
        )
        data["access_granted"] = list(self.access_granted)
        return data