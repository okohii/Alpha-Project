from __future__ import annotations

from typing import Any

from app.security import AccessDeniedError
from app.skills.files.service import FileManager
from app.tools.base import Tool, ToolPermission, ToolResult


class FileWriteTool(Tool):
    name = "file_write"
    description = "Cria um arquivo em um diretório autorizado"
    permission = ToolPermission.sensitive

    def __init__(self, file_manager: FileManager) -> None:
        self.file_manager = file_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            path = str(kwargs.get("path", ""))
            content = str(kwargs.get("content", ""))
            result = self.file_manager.create_file(path, content)
            return ToolResult(name=self.name, success=True, data=result)
        except (AccessDeniedError, OSError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo a criar"},
                "content": {"type": "string", "description": "Conteúdo do arquivo"},
            },
            "required": ["path"],
        }