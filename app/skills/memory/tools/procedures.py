from __future__ import annotations

from typing import Any

from app.memory.service import MemoryService
from app.tools.base import Tool, ToolPermission, ToolResult


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
            {
                "content": memory.content,
                "memory_type": memory.memory_type,
                "metadata": dict(memory.metadata or {}),
            }
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