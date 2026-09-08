from __future__ import annotations

from typing import Any

from app.security import AccessDeniedError
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.files.manager import FileManager


class FileInfoTool(Tool):
    name = "file_info"
    description = "Retorna metadados de um arquivo autorizado"
    permission = ToolPermission.read

    def __init__(self, file_manager: FileManager) -> None:
        self.file_manager = file_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = str(kwargs.get("path", ""))
            info = self.file_manager.file_info(path)
            return ToolResult(name=self.name, success=True, data=info)
        except (AccessDeniedError, OSError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo"},
            },
            "required": ["path"],
        }