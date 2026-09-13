"""Execução de código e comandos em sandbox local com limites de tempo."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.security import AccessDeniedError
from app.skills.files.service import FileManager

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


def _windows_job_object():
    """Cria um Job Object do Windows com KILL_ON_JOB_CLOSE.

    Quando o handle do job é fechado (processo pai morre/termina), o sistema
    encerra TODA a árvore — sandbox real de ciclo de vida, sem depender só de
    taskkill. Retorna None em POSIX ou se a criação falhar.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimit),
                ("IoInfo", ctypes.c_byte * 72),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(
            job,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        return job
    except Exception:  # pragma: no cover - defesa contra ambiente sem WinAPI
        return None


def _assign_to_job(job_handle, process) -> bool:
    if not job_handle or os.name != "nt":
        return False
    try:
        import ctypes

        handle = getattr(process, "_handle", None)
        if not handle:
            return False
        kernel32 = ctypes.windll.kernel32
        return bool(kernel32.AssignProcessToJobObject(job_handle, handle))
    except Exception:  # pragma: no cover
        return False


def _sandbox_prefix() -> list[str] | None:
    """Prefixo de sandbox do Linux (bwrap) quando disponível.

    - janela neutra de rede (--unshare-net);
    - namespaces de usuário + novas sessões;
    - sistema montado read-only (ro-bind de /usr,/bin,/lib,/lib64);
    - /tmp recém-criado (--tmpfs).

    Retorna None quando bwrap não está instalado (fallback = kill de árvore).
    Windows usa Job Object (nunca bwrap).
    """
    if os.name == "nt":
        return None
    if shutil.which("bwrap") is None:
        return None
    return [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-user-try",
        "--unshare-net",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
    ]


def _run_process(
    command: str | list[str], timeout: float, cwd: Path | None = None, shell: bool = False
) -> ExecResult:
    start = time.monotonic()
    creationflags = 0
    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        creationflags = 0x00000008 | 0x08000000
    job_handle = _windows_job_object()
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
        start_new_session=(os.name != "nt"),
        creationflags=creationflags,
    )
    # Assign ao job (se falhar — ex.: processo já em outra job — o kill por
    # árvore via taskkill/SIGKILL continua como fallback).
    _assign_to_job(job_handle, process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
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
    finally:
        if job_handle:
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(job_handle)
            except Exception:  # pragma: no cover
                pass
    return ExecResult(
        exit_code=process.returncode,
        stdout=_truncate(stdout),
        stderr=_truncate(stderr),
        duration_ms=(time.monotonic() - start) * 1000,
    )


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Mata a árvore de processos do sandbox (timeout não deixa órfãos).

    Windows: taskkill /T /F; POSIX: envia SIGKILL ao process group
    (start_new_session=True cria grupo próprio).
    """
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
    except Exception:  # pragma: no cover - melhor esforço
        try:
            process.kill()
        except Exception:
            pass


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
            prefix = _sandbox_prefix() or []
            command = [*prefix, sys.executable, "-X", "utf8", str(script)]
            return await asyncio.to_thread(_run_process, command, timeout, cwd)
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