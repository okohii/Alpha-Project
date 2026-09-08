"""Execução de código e comandos em sandbox local com limites de tempo."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.security import AccessDeniedError
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.files import FileManager

MAX_OUTPUT_CHARS = 20000


@dataclass(slots=True)
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": round(self.duration_ms, 1),
            "timed_out": self.timed_out,
        }


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [saída truncada: {len(text) - limit} caracteres omitidos]"


def _run_process(
    command: str | list[str], timeout: float, cwd: Path | None = None, shell: bool = False
) -> ExecResult:
    start = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=shell,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensivo
            stdout, stderr = "", "processo não respondeu ao encerramento forçado"
        return ExecResult(
            exit_code=None,
            stdout=_truncate(stdout),
            stderr=_truncate(stderr),
            duration_ms=(time.monotonic() - start) * 1000,
            timed_out=True,
        )
    return ExecResult(
        exit_code=process.returncode,
        stdout=_truncate(stdout),
        stderr=_truncate(stderr),
        duration_ms=(time.monotonic() - start) * 1000,
    )


class SandboxRunner:
    """Executa código Python ou comandos de shell de forma isolada.

    Ações padrão de segurança:
      - código Python roda em novo processo com o intérprete do projeto;
      - timeouts sempre aplicados e processos mortos ao estourar;
      - diretório de trabalho precisa estar nas pastas permitidas;
      - shell fica desabilitado por padrão (config ALLOW_SHELL_EXEC).
    """

    def __init__(self, file_manager: FileManager | None = None) -> None:
        self.file_manager = file_manager or FileManager()
        self.settings = get_settings()

    def resolve_workdir(self, workdir: str | None) -> Path | None:
        if not workdir:
            return None
        candidate = Path(workdir).expanduser().resolve()
        if self.file_manager.allowed_directories:
            try:
                return self.file_manager._ensure_allowed(candidate)
            except AccessDeniedError:
                return None
        return candidate

    async def run_python(
        self, code: str, workdir: str | None = None, timeout: float | None = None
    ) -> ExecResult:
        timeout = timeout or self.settings.code_exec_timeout_seconds
        cwd = self.resolve_workdir(workdir)
        sandbox_dir = Path(tempfile.gettempdir()) / "alpha_sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        script = sandbox_dir / f"alpha_{int(time.time() * 1000)}.py"
        script.write_text(code, encoding="utf-8")
        try:
            return await asyncio.to_thread(
                _run_process, [sys.executable, "-X", "utf8", str(script)], timeout, cwd
            )
        finally:
            try:
                script.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - limpeza best-effort
                pass

    async def run_shell(
        self, command: str, workdir: str | None = None, timeout: float | None = None
    ) -> ExecResult:
        timeout = timeout or self.settings.code_exec_timeout_seconds
        cwd = self.resolve_workdir(workdir)
        return await asyncio.to_thread(_run_process, command, timeout, cwd, True)


class RunCodeTool(Tool):
    name = "run_code"
    description = (
        "Executa código Python isolado no computador do usuário e devolve a saída "
        "(stdout/stderr, código de saída e tempo). Use para cálculos, scripts rápidos, "
        "processamento de arquivos, automação ou testes de lógica. O código roda no "
        "diretório de trabalho permitido; rede não é garantida nem bloqueada."
    )
    permission = ToolPermission.write

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
    permission = ToolPermission.write

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