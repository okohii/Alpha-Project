from __future__ import annotations

import asyncio
from typing import Any

from app.security import AccessDeniedError
from app.skills.files.service import FileManager
from app.tools.base import Tool, ToolPermission, ToolResult


class FileSearchTool(Tool):
    name = "file_search"
    description = (
        "Pesquisa arquivos por nome em um diretório autorizado. "
        'Para listar todos os arquivos de um diretório, use query vazio (""). '
        "Se nada corresponder à busca, retorna a listagem do diretório."
    )
    permission = ToolPermission.read

    def __init__(self, file_manager: FileManager) -> None:
        self.file_manager = file_manager

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            query = str(kwargs.get("query", ""))
            path = str(kwargs.get("path", "."))
            results = await asyncio.to_thread(self.file_manager.search_files, query, path)
            return ToolResult(name=self.name, success=True, data={"results": results})
        except (AccessDeniedError, OSError) as exc:
            return ToolResult(name=self.name, success=False, data={}, error=exc)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto ou padrão a pesquisar"},
                "path": {"type": "string", "description": "Diretório autorizado onde pesquisar"},
            },
            "required": ["query"],
        }