from __future__ import annotations

from enum import StrEnum

from app.security.command_policy import security_level_for
from app.security.permissions import SecurityLevel
from app.tools.base import ToolPermission

# Prefixo estrutural para confirmações de TOOL. Diferencia de forma
# inequívoca (não por heurística de formato) confirmação de tool sensível/
# arriscada de candidatos que são caminhos de filesystem. Nunca renderizado
# ao usuário: o runtime remove antes de exibir.
SENSITIVE_PREFIX = "\x00alpha-sensitive-action:"

# Ferramentas que EXECUTAM código/scripts (ação arbitrária não autorizada
# é bloqueada em nível de confirmação, nunca automática).
EXECUTE_TOOLS = frozenset(
    {"run_code", "run_shell", "task_execute", "procedure_run"}
)

# Ferramentas de OBSERVAÇÃO (leitura não destrutiva do ambiente): não
# alteram estado e não leem arquivos do usuário.
OBSERVE_TOOLS = frozenset(
    {
        "browser_text",
        "browser_html",
        "browser_screenshot",
        "web_search",
        "read_ui",
        "screenshot",
        "verify_screen",
        "list_apps",
        "list_monitors",
        "time",
        "system_info",
        "system_config",
    }
)

# Captura sensorial (tela/câmera) exige confirmação MESMO em modo read/observe:
# capturar a área de trabalho inteira ou ativar a câmera física é um ato de
# privacidade que não pode ser automático.
PRIVACY_SENSITIVE_OBSERVE = frozenset(
    {"screenshot", "verify_screen", "detect_camera"}
)


class ToolAction(StrEnum):
    """Tipo de ação separado para política de least privilege.

    Vai além da tríade read/write/sensitive: observação (não destrutiva,
    ambiente), leitura (arquivos/dados) e execução (código arbitrário) são
    distinguidas para decisão e auditoria.
    """

    observe = "observe"
    read = "read"
    write = "write"
    execute = "execute"
    sensitive = "sensitive"


def classify_action(tool_name: str, permission: ToolPermission | None = None) -> ToolAction:
    """Classifica a ação de uma tool nas 5 categorias de política.

    A autorização continua em 3 níveis (``ToolPermission``); esta classificação
    documenta O QUE a ação é (para auditoria e decisão de confirmação).
    """
    if permission is ToolPermission.sensitive or tool_name in EXECUTE_TOOLS:
        if tool_name in EXECUTE_TOOLS:
            return ToolAction.execute
        return ToolAction.sensitive
    if tool_name in OBSERVE_TOOLS:
        return ToolAction.observe
    if permission is ToolPermission.write:
        return ToolAction.write
    return ToolAction.read


def risk_requires_confirmation(
    tool_name: str, permission: ToolPermission | None = None
) -> bool:
    """Política de confirmação:

    - observe/read  -> automático (sem confirmação);
    - sensitive     -> confirmação obrigatória por padrão;
    - write         -> depende do risco (medium/high exigem confirmação).
    """
    if permission is ToolPermission.sensitive or tool_name in EXECUTE_TOOLS:
        return True
    if tool_name in PRIVACY_SENSITIVE_OBSERVE:
        return True
    if permission is ToolPermission.write:
        return security_level_for(tool_name) in (SecurityLevel.medium, SecurityLevel.high)
    return False