from __future__ import annotations

from typing import Any

from app.memory.episode import detect_kind
from app.memory.service import MemoryService
from app.tools.base import Tool, ToolPermission, ToolResult


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
            data={"memories": [memory.model_dump() for memory in memories]},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termo de busca nas memórias"},
            },
            "required": ["query"],
        }


class MemorySaveTool(Tool):
    name = "memory_save"
    description = "Salva uma memória explícita"
    permission = ToolPermission.write

    def __init__(self, memory_service: MemoryService) -> None:
        self.memory_service = memory_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        content = str(kwargs.get("content", ""))
        memory_type = str(kwargs.get("memory_type") or detect_kind(content))
        memory = await self.memory_service.save_memory(
            content=content, memory_type=memory_type, source="explicit"
        )
        payload = memory.model_dump() if memory else {"saved": False}
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


class ProcedureSaveTool(Tool):
    name = "procedure_save"
    description = (
        "Grava um procedimento/rotina executável pelo agente: nome, descrição e passos. "
        "Use quando o usuário mostrar uma sequência repetível que vale a pena lembrar."
    )
    permission = ToolPermission.write

    def __init__(self, memory_service: MemoryService) -> None:
        self.memory_service = memory_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        name = str(kwargs.get("name", "")).strip()
        description = str(kwargs.get("description", "")).strip()
        steps = kwargs.get("steps", [])
        if isinstance(steps, str):
            steps = [line.strip() for line in steps.splitlines() if line.strip()]
        steps_text = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
        content = f"Procedimento \u201c{name}\u201d: {description}. Passos:\n{steps_text}"
        memory = await self.memory_service.save_memory(
            content=content,
            memory_type="procedimento",
            source="procedure_save",
            importance=1.0,
            metadata={"procedure": True, "name": name, "steps": list(steps)},
        )
        payload = memory.model_dump() if memory else {"saved": False}
        return ToolResult(name=self.name, success=True, data={"procedure": name, **payload})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome curto do procedimento"},
                "description": {"type": "string", "description": "Para que serve o procedimento"},
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordem de passos que o agente deve executar",
                },
            },
            "required": ["name", "steps"],
        }


class ProcedureRunTool(Tool):
    name = "procedure_run"
    description = "Busca um procedimento salvo pelo nome e devolve seus passos para execução"
    permission = ToolPermission.read

    def __init__(self, memory_service: MemoryService) -> None:
        self.memory_service = memory_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        name = str(kwargs.get("name", "")).lower()
        memories = await self.memory_service.search_memories(
            f"procedimento {name}", limit=10
        )
        matches = [
            memory.model_dump()
            for memory in memories
            if memory.memory_type == "procedimento"
            and (
                not name
                or name in memory.content.lower()
                or name in str((memory.metadata or {}).get("name", "")).lower()
            )
        ]
        return ToolResult(name=self.name, success=True, data={"procedures": matches})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Nome do procedimento"}},
            "required": ["name"],
        }
