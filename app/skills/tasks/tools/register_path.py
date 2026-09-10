from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class TaskRegisterPathTool(Tool):
    name = "task_register_path"
    description = "Registra um diretório ou arquivo permitido para uso do executor de tarefas."
    permission = ToolPermission.sensitive

    def __init__(self, task_service: Any) -> None:
        self.task_service = task_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        record = await self.task_service.register_allowed_path(
            path=str(kwargs.get("path", "")),
            entry_type=str(kwargs.get("entry_type", "directory")),
            source=str(kwargs.get("source", "task_executor")),
        )
        return ToolResult(
            name=self.name,
            success=True,
            data={"path": record.path, "entry_type": record.entry_type},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "entry_type": {"type": "string"},
                "source": {"type": "string"},
            },
            "required": ["path"],
        }