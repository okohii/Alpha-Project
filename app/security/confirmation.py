from __future__ import annotations

from app.security.command_policy import security_level_for
from app.security.permissions import SecurityLevel


class PermissionManager:
    """Decide a política de confirmação com base no nível de risco da ferramenta."""

    def __init__(
        self,
        require_confirmation: bool = True,
        high_risk_require_confirmation: bool = True,
    ) -> None:
        self.require_confirmation = require_confirmation
        self.high_risk_require_confirmation = high_risk_require_confirmation

    def needs_confirmation(self, tool_name: str) -> bool:
        level = security_level_for(tool_name)
        if level is SecurityLevel.high:
            return self.high_risk_require_confirmation
        if level is SecurityLevel.medium:
            return self.require_confirmation
        return False