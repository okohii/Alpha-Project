from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.documents.indexer import DocumentIndexer
from app.tools.base import Tool, ToolPermission, ToolResult


class DocumentSearchTool(Tool):
    name = "document_search"
    description = (
        "Busca nos documentos indexados do projeto/computador e devolve trechos "
        "relevantes com a fonte (caminho do arquivo). Use quando a resposta precisar "
        "ser baseada no conteúdo de arquivos locais, NÃO inventar informações."
    )
    permission = ToolPermission.read

    def __init__(self, indexer_factory: Callable[[], DocumentIndexer]) -> None:
        self._indexer_factory = indexer_factory

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(name=self.name, success=False, data={}, error="Informe a consulta.")
        try:
            limit = int(kwargs.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        result = await self._indexer_factory().search_documents(query, limit=limit)
        return ToolResult(name=self.name, success=True, data=result)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Pergunta/termo para buscar nos documentos",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número de trechos a retornar (padrão 5)",
                },
            },
            "required": ["query"],
        }