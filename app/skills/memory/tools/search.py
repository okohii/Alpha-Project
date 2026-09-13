from __future__ import annotations

from typing import Any

from app.memory.service import MemoryService
from app.tools.base import Tool, ToolPermission, ToolResult


def _semantic_view(memory: Any) -> dict[str, Any]:
    """Vista semântica para o LLM: contexto útil, sem vetor/metadata interna.

    O modelo precisa do CONTEÚDO relevante, não da representação técnica.
    (Parte 31): vetores, metadados internos e identificadores não são
    informação semântica.
    """
    return {
        "content": memory.content,
        "memory_type": memory.memory_type,
        "importance": memory.importance,
    }


class MemorySearchTool(Tool):
    name = "memory_search"
    description = "Busca memórias relevantes"
    permission = ToolPermission.read

    def __init__(self, memory_service: MemoryService) -> None:
        self.memory_service = memory_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", ""))
        memories = await self.memory_service.search_memories(query)
        return ToolResult(
            name=self.name,
            success=True,
            data={"memories": [_semantic_view(memory) for memory in memories]},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca nas memórias"},
            },
            "required": ["query"],
        }