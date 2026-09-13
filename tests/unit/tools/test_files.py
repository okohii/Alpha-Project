from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.security import AccessDeniedError
from app.skills.files import FileManager, FileWriteTool


def test_file_manager_blocks_path_traversal(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "note.txt").write_text("hello", encoding="utf-8")
    manager = FileManager([allowed])

    with pytest.raises(AccessDeniedError):
        manager.read_file(str(tmp_path / ".." / "secret.txt"))


def test_file_manager_lists_and_reads(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    file_path = allowed / "script.py"
    file_path.write_text("print('ok')", encoding="utf-8")
    manager = FileManager([allowed])

    entries = manager.list_directory(str(allowed))
    assert entries[0]["name"] == "script.py"
    assert manager.read_file(str(file_path)) == "print('ok')"


def test_file_manager_search_files(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "app.py").write_text("x = 1", encoding="utf-8")
    manager = FileManager([allowed])

    results = manager.search_files("py", str(allowed))
    assert results and results[0]["name"] == "app.py"


def test_file_manager_search_falls_back_to_listing_when_no_match(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "app.py").write_text("x = 1", encoding="utf-8")
    manager = FileManager([allowed])

    results = manager.search_files("nada-corresponde", str(allowed))
    assert results and results[0]["name"] == "app.py"


def test_file_write_tool_captures_oserror():
    class FailingManager:
        def create_file(self, path: str, content: str):
            raise PermissionError(13, "Permission denied", path)

    tool = FileWriteTool(FailingManager())  # type: ignore[arg-type]
    result = asyncio.run(tool.execute(path="C:/x/y.txt", content="oi"))

    assert result.success is False
    assert isinstance(result.error, PermissionError)
