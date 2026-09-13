from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class TaskListTool(Tool):
    name = "task_list"
    description = "Lista tarefas persistentes do executor."
    permission = ToolPermission.read

    def __init__(self, task_service: Any) -> None:
        self.task_service = task_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        tasks = await self.task_service.list_tasks(limit=int(kwargs.get("limit", 20)))
        return ToolResult(
            name=self.name,
            success=True,
            data={"tasks": [task.__dict__ for task in tasks]},
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"limit": {"type": "integer"}}}