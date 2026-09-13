from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class TaskCreateTool(Tool):
    name = "task_create"
    description = (
        "Cria uma tarefa persistente para o executor automatizar ações locais e de desenvolvimento."
    )
    permission = ToolPermission.write

    def __init__(self, task_service: Any) -> None:
        self.task_service = task_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        task = await self.task_service.create_task(
            title=str(kwargs.get("title", "Tarefa")),
            instruction=str(kwargs.get("instruction", "")),
            action=str(kwargs.get("action", "")),
            params=dict(kwargs.get("params") or {}),
        )
        return ToolResult(name=self.name, success=True, data={"task": task.__dict__})

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "instruction": {"type": "string"},
                "action": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["title", "action"],
        }