from __future__ import annotations

import pytest

from app.skills.shell import RunCodeTool, RunShellTool, SandboxRunner


@pytest.mark.anyio
async def test_run_python_returns_stdout():
    runner = SandboxRunner()
    result = await runner.run_python('print("olá do sandbox")')

    assert result.exit_code == 0
    assert not result.timed_out
    assert "olá do sandbox" in result.stdout


@pytest.mark.anyio
async def test_run_python_captures_error():
    runner = SandboxRunner()
    result = await runner.run_python("raise ValueError('boom')")

    assert result.exit_code == 1
    assert "ValueError" in result.stderr


@pytest.mark.anyio
async def test_run_python_respects_timeout():
    runner = SandboxRunner()
    result = await runner.run_python("import time; time.sleep(5)", timeout=0.5)

    assert result.timed_out is True
    assert result.exit_code is None


@pytest.mark.anyio
async def test_run_code_tool_success(tmp_path):
    tool = RunCodeTool()
    result = await tool.execute(code='print("soma:", 2 + 2)', workdir=str(tmp_path))

    assert result.success is True
    assert result.data["exit_code"] == 0
    assert "soma: 4" in result.data["stdout"]


@pytest.mark.anyio
async def test_run_code_tool_requires_code():
    tool = RunCodeTool()
    result = await tool.execute(code="")

    assert result.success is False
    assert "Informe o código" in result.error


@pytest.mark.anyio
async def test_run_code_tool_flags_failure():
    tool = RunCodeTool()
    result = await tool.execute(code="import this_does_not_exist")

    assert result.success is False
    assert result.data["exit_code"] != 0


@pytest.mark.anyio
async def test_run_shell_disabled_by_default():
    tool = RunShellTool()
    result = await tool.execute(command="echo oi")

    assert result.success is False
    assert "desabilitada" in result.error


@pytest.mark.anyio
async def test_run_shell_works_when_enabled(monkeypatch):
    tool = RunShellTool()
    tool.settings.allow_shell_exec = True

    result = await tool.execute(command="echo ola-shell")

    assert result.success is True
    assert "ola-shell" in result.data["stdout"]


@pytest.mark.anyio
async def test_run_shell_errors_when_command_fails(monkeypatch):
    tool = RunShellTool()
    tool.settings.allow_shell_exec = True

    result = await tool.execute(command="exit 3")

    assert result.success is False
    assert result.data["exit_code"] == 3