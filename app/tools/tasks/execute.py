from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class TaskExecuteTool(Tool):
    name = "task_execute"
    description = "Executa uma tarefa persistente previamente criada."
    permission = ToolPermission.sensitive

    def __init__(self, task_service: Any) -> None:
        self.task_service = task_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        task_id = str(kwargs.get("task_id", ""))
        result = await self.task_service.execute_task(task_id)
        return ToolResult(
            name=self.name,
            success=result.success,
            data={"task_id": task_id, "result": result.result, "error": result.error},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        }