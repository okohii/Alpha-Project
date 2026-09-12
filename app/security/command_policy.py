from __future__ import annotations

from app.security.permissions import SecurityLevel

# Ferramentas cuja execução exige confirmação em qualquer interface
# (mapeada por ToolPermission.sensitive + este nível alto).
HIGH_RISK_TOOLS = {
    "run_shell",
    "run_code",
    "browser_js",
    "task_execute",
    "file_write",
}

MEDIUM_RISK_TOOLS = {
    "file_write",
    "browser_click",
    "type_text",
    "press_key",
    "mouse_click",
    "mouse_scroll",
    "click_text",
    "memory_save",
    "memory_delete",
    "task_create",
    "reminder_create",
    "reminder_delete",
    "calendar_create",
    "calendar_delete",
}


def security_level_for(tool_name: str) -> SecurityLevel:
    if tool_name in HIGH_RISK_TOOLS:
        return SecurityLevel.high
    if tool_name in MEDIUM_RISK_TOOLS:
        return SecurityLevel.medium
    return SecurityLevel.low
