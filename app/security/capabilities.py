"""Capabilities: capacidade concreta exigida para executar uma operação.

O LLM jamais é tratado como componente de segurança. Cada tool possui um
conjunto EXPLÍCITO de capabilities; qualquer decisão de risco/autorização/
confirmação é derivada delas — nunca de heurística textual ou de subset do
prompt.

Princípios:
- ``WRITE_FILE != EXECUTE_CODE != EXECUTE_SHELL``;
- uma operação anterior NÃO concede automaticamente a próxima;
- ``close_app``/``open_url``/``open_file``/``move_app`` são classificados pela
  natureza real (controle de sistema / rede / execução de software), não por
  ``permission == write``.
"""
from __future__ import annotations

from enum import StrEnum

from app.security.permissions import SecurityLevel


class Capability(StrEnum):
    READ = "read"
    WRITE = "write"
    WRITE_FILE = "write_file"
    FILE_OPEN = "file_open"
    NETWORK = "network"
    BROWSER_NAVIGATION = "browser_navigation"
    BROWSER_DOM_READ = "browser_dom_read"
    BROWSER_DOM_WRITE = "browser_dom_write"
    BROWSER_JS_EXECUTION = "browser_js_execution"
    EXECUTE = "execute"
    EXECUTE_SHELL = "execute_shell"
    EXECUTE_CODE = "execute_code"
    SYSTEM_CONTROL = "system_control"
    AUTOMATION = "automation"
    SCREEN_CAPTURE = "screen_capture"
    GIT_LOCAL = "git_local"
    GIT_NETWORK = "git_network"
    SCHEDULE = "schedule"
    MACRO_EXECUTION = "macro_execution"


# Capabilities que NUNCA podem ser auto-aprovadas via flag: execução arbitrária
# ou controle de sistema. Uma aprovação anterior (mesmo do usuário) não é
# transferível para estas — exigem confirmação por chamada.
NON_AUTO_APPROVABLE = frozenset(
    {
        Capability.EXECUTE,
        Capability.EXECUTE_CODE,
        Capability.EXECUTE_SHELL,
        Capability.BROWSER_JS_EXECUTION,
        Capability.FILE_OPEN,  # abre com app padrão — pode executar software
        Capability.GIT_NETWORK,
        Capability.MACRO_EXECUTION,
        Capability.SYSTEM_CONTROL,  # C2: escrita em disco/controle de sistema NUNCA por flag
    }
)

_CAPABILITY_MAP: dict[str, frozenset[Capability]] = {
    # Observação
    "file_search": frozenset({Capability.READ}),
    "file_read": frozenset({Capability.READ}),
    "file_info": frozenset({Capability.READ}),
    "document_search": frozenset({Capability.READ}),
    "list_apps": frozenset({Capability.READ}),
    "list_monitors": frozenset({Capability.READ}),
    "read_ui": frozenset({Capability.READ}),
    "system_info": frozenset({Capability.READ}),
    "system_config": frozenset({Capability.READ}),
    "time": frozenset({Capability.READ}),
    "memory_search": frozenset({Capability.READ}),
    "task_list": frozenset({Capability.READ}),
    "reminder_list": frozenset({Capability.READ}),
    "calendar_list": frozenset({Capability.READ}),
    "macro_list": frozenset({Capability.READ}),
    "macro_schedules": frozenset({Capability.READ}),
    "web_search": frozenset({Capability.READ}),
    # Tela / captura
    "screenshot": frozenset({Capability.SCREEN_CAPTURE}),
    "verify_screen": frozenset({Capability.SCREEN_CAPTURE, Capability.READ}),
    "detect_camera": frozenset({Capability.SCREEN_CAPTURE}),
    # Arquivos
    "file_write": frozenset({Capability.WRITE_FILE, Capability.SYSTEM_CONTROL}),
    "open_file": frozenset({Capability.FILE_OPEN}),
    # Apps / sistema
    "open_app": frozenset({Capability.EXECUTE, Capability.SYSTEM_CONTROL}),
    "close_app": frozenset({Capability.SYSTEM_CONTROL, Capability.EXECUTE}),
    "move_app": frozenset({Capability.SYSTEM_CONTROL}),
    # Rede / navegador
    "open_url": frozenset({Capability.NETWORK, Capability.BROWSER_NAVIGATION}),
    "browser_open": frozenset({Capability.BROWSER_NAVIGATION, Capability.NETWORK}),
    "browser_text": frozenset({Capability.BROWSER_DOM_READ}),
    "browser_html": frozenset({Capability.BROWSER_DOM_READ}),
    "browser_wait": frozenset({Capability.BROWSER_DOM_READ}),
    "browser_screenshot": frozenset({Capability.BROWSER_DOM_READ}),
    "browser_click": frozenset({Capability.BROWSER_DOM_WRITE}),
    "browser_js": frozenset(
        {Capability.BROWSER_JS_EXECUTION, Capability.BROWSER_DOM_WRITE, Capability.NETWORK}
    ),
    # Automação GUI
    "type_text": frozenset({Capability.AUTOMATION}),
    "press_key": frozenset({Capability.AUTOMATION}),
    "mouse_click": frozenset({Capability.AUTOMATION}),
    "mouse_scroll": frozenset({Capability.AUTOMATION}),
    "click_text": frozenset({Capability.AUTOMATION}),
    "windows_search": frozenset({Capability.AUTOMATION}),
    # Execução arbitrária
    "run_code": frozenset({Capability.EXECUTE_CODE}),
    "run_shell": frozenset({Capability.EXECUTE_SHELL}),
    "procedure_run": frozenset({Capability.EXECUTE}),
    "task_execute": frozenset({Capability.EXECUTE, Capability.GIT_LOCAL, Capability.GIT_NETWORK}),
    "task_register_path": frozenset({Capability.SYSTEM_CONTROL}),
    # Memória / escrita
    "memory_save": frozenset({Capability.WRITE}),
    "memory_delete": frozenset({Capability.WRITE}),
    "procedure_save": frozenset({Capability.WRITE}),
    "task_create": frozenset({Capability.WRITE}),
    "reminder_create": frozenset({Capability.SCHEDULE, Capability.WRITE}),
    "reminder_delete": frozenset({Capability.WRITE}),
    "calendar_create": frozenset({Capability.WRITE}),
    "calendar_delete": frozenset({Capability.WRITE}),
    # Macros
    "macro_run": frozenset({Capability.MACRO_EXECUTION, Capability.EXECUTE}),
    "macro_create": frozenset({Capability.MACRO_EXECUTION, Capability.WRITE}),
    "macro_delete": frozenset({Capability.MACRO_EXECUTION, Capability.WRITE}),
    "macro_schedule": frozenset({Capability.MACRO_EXECUTION, Capability.SCHEDULE}),
    "macro_schedule_edit": frozenset({Capability.MACRO_EXECUTION, Capability.SCHEDULE}),
    "macro_schedule_delete": frozenset({Capability.MACRO_EXECUTION, Capability.SCHEDULE}),
}


def capabilities_for(tool_name: str) -> frozenset[Capability]:
    """Capabilities de uma tool (owner explícito, sem reflexão)."""
    name = (tool_name or "").split("(", 1)[0]
    return _CAPABILITY_MAP.get(name, frozenset({Capability.READ}))


def is_auto_approvable(tool_name: str) -> bool:
    """Pode ser autorizado por ``agent_auto_approve_sensitive``?

    FALSE para qualquer capability de execução arbitrária/controle — impede a
    cadeia write → execute (Parte 4/H2).
    """
    return not bool(capabilities_for(tool_name) & NON_AUTO_APPROVABLE)


def risk_level_for_tool(tool_name: str) -> SecurityLevel:
    """Risco derivado da natureza real da operação (Parte 21)."""
    caps = capabilities_for(tool_name)
    if caps & {
        Capability.EXECUTE_SHELL,
        Capability.EXECUTE_CODE,
        Capability.BROWSER_JS_EXECUTION,
        Capability.GIT_NETWORK,
        Capability.SYSTEM_CONTROL,
        Capability.FILE_OPEN,
        Capability.MACRO_EXECUTION,
        Capability.EXECUTE,
        Capability.WRITE_FILE,
    }:
        return SecurityLevel.high
    if caps & {
        Capability.NETWORK,
        Capability.BROWSER_NAVIGATION,
        Capability.BROWSER_DOM_WRITE,
        Capability.SCHEDULE,
        Capability.AUTOMATION,
        Capability.WRITE_FILE,
        Capability.WRITE,
        Capability.GIT_LOCAL,
        Capability.SCREEN_CAPTURE,  # captura de tela/câmera é sensível a privacidade
    }:
        return SecurityLevel.medium
    return SecurityLevel.low


__all__ = [
    "Capability",
    "NON_AUTO_APPROVABLE",
    "capabilities_for",
    "is_auto_approvable",
    "risk_level_for_tool",
]