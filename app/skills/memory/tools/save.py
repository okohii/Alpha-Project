from __future__ import annotations

from typing import Any

from app.memory.episode import detect_kind
from app.memory.service import MemoryService
from app.tools.base import Tool, ToolPermission, ToolResult


class MemorySaveTool(Tool):
    name = "memory_save"
    description = (
        "Salva uma memória explícita do usuário (fato, preferência, perfil, "
        "URL/dado reutilizável). Use para REGISTRAR algo que o usuário quer "
        "reutilizar (ex.: 'meu perfil do github é https://github.com/okohii') e "
        "para CORRIGIR uma memória anterior: primeiro memory_search para achar a "
        "errada, delete-a com memory_delete e então memory_save com o valor certo."
    )
    permission = ToolPermission.write

    def __init__(self, memory_service: MemoryService) -> None:
        self.memory_service = memory_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        content = str(kwargs.get("content", "")).strip()
        if not content:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Informe o conteúdo da memória a salvar.",
            )
        memory_type = str(kwargs.get("memory_type") or detect_kind(content))
        memory = await self.memory_service.save_memory(
            content=content,
            memory_type=memory_type,
            source="explicit",
            persist_if_relevant=False,
        )
        if memory is None:
            return ToolResult(
                name=self.name,
                success=False,
                data={},
                error="Não foi possível salvar a memória.",
            )
        payload = memory.model_dump()
        return ToolResult(name=self.name, success=True, data=payload)

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Conteúdo da memória a salvar"},
                "memory_type": {"type": "string", "description": "Tipo de memória"},
            },
            "required": ["content"],
        }