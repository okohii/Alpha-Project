from __future__ import annotations

from typing import Any

from app.security import AccessDeniedError
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.files.manager import FileManager


class FileReadTool(Tool):
    name = "file_read"
    description = "Lê um arquivo autorizado"
    permission = ToolPermission.read

    def __init__(self, file_manager: FileManager) -> None:
        self.file_manager = file_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = str(kwargs.get("path", ""))
            content = self.file_manager.read_file(path)
            return ToolResult(name=self.name, success=True, data={"path": path, "content": content})
        except (AccessDeniedError, OSError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo autorizado"},
            },
            "required": ["path"],
        }