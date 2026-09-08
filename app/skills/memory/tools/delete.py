from __future__ import annotations

from typing import Any

from app.memory.service import MemoryService
from app.tools.base import Tool, ToolPermission, ToolResult


class MemoryDeleteTool(Tool):
    name = "memory_delete"
    description = "Remove uma memória pelo identificador"
    permission = ToolPermission.write

    def __init__(self, memory_service: MemoryService) -> None:
        self.memory_service = memory_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        memory_id = str(kwargs.get("memory_id", ""))
        await self.memory_service.delete_memory(memory_id)
        return ToolResult(name=self.name, success=True, data={"deleted": memory_id})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "Identificador da memória",
                }
            },
            "required": ["memory_id"],
        }