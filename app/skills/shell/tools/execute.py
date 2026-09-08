from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.skills.files.service import FileManager
from app.skills.shell.service import SandboxRunner
from app.tools.base import Tool, ToolPermission, ToolResult


class RunCodeTool(Tool):
    name = "run_code"
    description = (
        "Executa código Python isolado no computador do usuário e devolve a saída "
        "(stdout/stderr, código de saída e tempo). Use para cálculos, scripts rápidos, "
        "processamento de arquivos, automação ou testes de lógica. O código roda no "
        "diretório de trabalho permitido; rede não é garantida nem bloqueada."
    )
    permission = ToolPermission.sensitive

    def __init__(self, file_manager: FileManager | None = None) -> None:
        self.runner = SandboxRunner(file_manager)

    async def execute(self, **kwargs: Any) -> ToolResult:
        code = str(kwargs.get("code", ""))
        if not code.strip():
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe o código a executar."
            )
        workdir = kwargs.get("workdir")
        timeout_s = kwargs.get("timeout_s")
        try:
            timeout = float(timeout_s) if timeout_s else 0.0
        except (TypeError, ValueError):
            timeout = 0.0
        result = await self.runner.run_python(
            code, workdir=str(workdir) if workdir else None, timeout=timeout or None
        )
        data = result.to_dict()
        success = result.exit_code == 0 and not result.timed_out
        error = result.stderr[:2000] if not success else None
        return ToolResult(name=self.name, success=success, data=data, error=error)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Código Python a executar"},
                "workdir": {
                    "type": "string",
                    "description": "Diretório de trabalho (opcional)",
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Timeout em segundos (padrão do sistema)",
                },
            },
            "required": ["code"],
        }


class RunShellTool(Tool):
    name = "run_shell"
    description = (
        "Executa um comando de shell no computador do usuário e devolve a saída. "
        "Somente funciona se ALLOW_SHELL_EXEC=true no .env, pois dá acesso amplo ao sistema."
    )
    permission = ToolPermission.sensitive

    def __init__(self, file_manager: FileManager | None = None) -> None:
        self.runner = SandboxRunner(file_manager)
        self.settings = get_settings()

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self.settings.allow_shell_exec:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Execução de shell está desabilitada (ALLOW_SHELL_EXEC=false no .env).",
            )
        command = str(kwargs.get("command", ""))
        if not command.strip():
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe o comando a executar."
            )
        workdir = kwargs.get("workdir")
        timeout_s = kwargs.get("timeout_s")
        try:
            timeout = float(timeout_s) if timeout_s else 0.0
        except (TypeError, ValueError):
            timeout = 0.0
        result = await self.runner.run_shell(
            command, workdir=str(workdir) if workdir else None, timeout=timeout or None
        )
        data = result.to_dict()
        success = result.exit_code == 0 and not result.timed_out
        error = result.stderr[:2000] if not success else None
        return ToolResult(name=self.name, success=success, data=data, error=error)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando de shell a executar"},
                "workdir": {"type": "string", "description": "Diretório de trabalho (opcional)"},
                "timeout_s": {"type": "number", "description": "Timeout em segundos"},
            },
            "required": ["command"],
        }