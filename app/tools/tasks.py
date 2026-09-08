from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolPermission, ToolResult


class TaskCreateTool(Tool):
    name = "task_create"
    description = "Cria uma tarefa persistente para o executor automatizar ações locais e de desenvolvimento."
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


class TaskExecuteTool(Tool):
    name = "task_execute"
    description = "Executa uma tarefa persistente previamente criada."
    permission = ToolPermission.write

    def __init__(self, task_service: Any) -> None:
        self.task_service = task_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        task_id = str(kwargs.get("task_id", ""))
        result = await self.task_service.execute_task(task_id)
        return ToolResult(name=self.name, success=result.success, data={"task_id": task_id, "result": result.result, "error": result.error})

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}


class TaskListTool(Tool):
    name = "task_list"
    description = "Lista tarefas persistentes do executor."
    permission = ToolPermission.read

    def __init__(self, task_service: Any) -> None:
        self.task_service = task_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        tasks = await self.task_service.list_tasks(limit=int(kwargs.get("limit", 20)))
        return ToolResult(name=self.name, success=True, data={"tasks": [task.__dict__ for task in tasks]})

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"limit": {"type": "integer"}}}


class TaskRegisterPathTool(Tool):
    name = "task_register_path"
    description = "Registra um diretório ou arquivo permitido para uso do executor de tarefas."
    permission = ToolPermission.write

    def __init__(self, task_service: Any) -> None:
        self.task_service = task_service

    async def execute(self, **kwargs: Any) -> ToolResult:
        record = await self.task_service.register_allowed_path(
            path=str(kwargs.get("path", "")),
            entry_type=str(kwargs.get("entry_type", "directory")),
            source=str(kwargs.get("source", "task_executor")),
        )
        return ToolResult(name=self.name, success=True, data={"path": record.path, "entry_type": record.entry_type})

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
