"""Gestão de processos no Windows: listar aplicativos em execução e encerrá-los."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.computer.application import ApplicationLauncher


def running_process_names() -> list[str]:
    if os.name != "nt":
        return []
    try:
        output = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names: list[str] = []
    for line in output.splitlines():
        parts = line.split('","')
        if len(parts) >= 2:
            name = parts[0].strip('"').strip()
            if name.lower().endswith(".exe"):
                names.append(name.lower())
    return names


def close_processes(names: list[str]) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("Fechar aplicativos só é suportado no Windows.")
    killed: list[str] = []
    errors: list[str] = []
    for name in {n.lower() for n in names if n}:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", name],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            killed.append(name)
        else:
            detail = (result.stderr or result.stdout or "").strip()
            errors.append(detail if detail else name)
    return {"killed": killed, "errors": errors}


def candidate_process_names(app_name: str, resolved_path: str | None) -> list[str]:
    names: list[str] = []
    if resolved_path:
        path = Path(resolved_path)
        names.append(path.stem.lower())
        names.append(path.name.lower())
    norm = app_name.strip().lower()
    if norm:
        names.append(norm)
    return list(dict.fromkeys(names))


def _match_running(candidates: list[str], running: list[str]) -> list[str]:
    running_noext = [name[:-4] for name in running]
    matched: list[str] = []
    for candidate in candidates:
        c = candidate.lower()
        for name, noext in zip(running, running_noext, strict=True):
            same = c == noext or c == name
            close = len(c) >= 4 and (c in noext or noext in c)
            if (same or close) and name not in matched:
                matched.append(name)
    return matched


class CloseAppTool(Tool):
    name = "close_app"
    description = (
        "Fecha um aplicativo que está aberto no computador pelo nome. "
        "Ex.: 'feche o chrome', 'fecha o discord'. Encerra o processo do programa."
    )
    permission = ToolPermission.write

    def __init__(self, launcher: ApplicationLauncher) -> None:
        self.launcher = launcher

    async def execute(self, **kwargs: Any) -> ToolResult:
        app = str(kwargs.get("app", "")).strip()
        if not app:
            return ToolResult(
                name=self.name, success=False, data={}, error="Informe o aplicativo a fechar."
            )
        try:
            info = self.launcher.resolve(app)
        except ValueError as exc:
            return ToolResult(name=self.name, success=False, data={}, error=str(exc))

        running = running_process_names()
        candidates = candidate_process_names(info.get("app", ""), info.get("path"))
        matched = _match_running(candidates, running)
        if not matched:
            return ToolResult(
                name=self.name,
                success=True,
                data={"app": info.get("app", app), "running": False},
                error=None,
            )
        result = close_processes(matched)
        return ToolResult(
            name=self.name,
            success=not result["errors"],
            data={"app": info.get("app", app), **result},
            error="; ".join(result["errors"]) if result["errors"] else None,
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Nome do aplicativo a fechar (ex.: 'chrome')",
                },
            },
            "required": ["app"],
        }