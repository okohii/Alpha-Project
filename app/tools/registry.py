from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.llm.vision import OllamaVisionProvider
from app.llm.vision_verify import get_vision_verifier
from app.memory.service import MemoryService
from app.tools.apps import ApplicationLauncher, ListAppsTool, OpenAppTool, OpenFileTool, OpenUrlTool
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.browser_tools import (
    BrowserClickTool,
    BrowserHtmlTool,
    BrowserJsTool,
    BrowserOpenTool,
    BrowserScreenshotTool,
    BrowserTextTool,
    BrowserWaitTool,
)
from app.tools.calendar_tools import (
    CalendarCreateTool,
    CalendarDeleteTool,
    CalendarListTool,
)
from app.tools.code import RunCodeTool, RunShellTool
from app.tools.files import FileInfoTool, FileManager, FileReadTool, FileSearchTool, FileWriteTool
from app.tools.gui import (
    MouseClickTool,
    MouseScrollTool,
    PressKeyTool,
    ScreenshotTool,
    VerifyScreenTool,
)
from app.tools.memory import (
    MemoryDeleteTool,
    MemorySaveTool,
    MemorySearchTool,
    ProcedureRunTool,
    ProcedureSaveTool,
)
from app.tools.pc import CloseAppTool, TypeTextTool
from app.tools.reminders import ReminderCreateTool, ReminderDeleteTool, ReminderListTool
from app.tools.system import SystemConfigTool, SystemInfoTool
from app.tools.tasks import TaskCreateTool, TaskExecuteTool, TaskListTool, TaskRegisterPathTool
from app.tools.time import TimeTool
from app.tools.uia import ClickTextTool, ReadUiTool
from app.tools.web import DuckDuckGoHtmlSearchProvider, WebSearchTool
from app.tools.windows import ListMonitorsTool, MoveAppTool


class ToolNotFoundError(KeyError):
    pass


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, Tool]

    def list(self, permissions: set[ToolPermission] | None = None) -> list[Tool]:
        if permissions is None:
            return list(self.tools.values())
        return [tool for tool in self.tools.values() if tool.permission in permissions]

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise ToolNotFoundError(name)
        return self.tools[name]

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        return await tool.execute(**kwargs)

    def schemas(self, permissions: set[ToolPermission] | None = None) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self.list(permissions)]


def build_default_tool_registry(
    file_manager: FileManager | None = None,
    memory_service: MemoryService | None = None,
    task_service: Any | None = None,
    reminder_service: Any | None = None,
    calendar_service: Any | None = None,
) -> ToolRegistry:
    file_manager = file_manager or FileManager()
    app_launcher = ApplicationLauncher()
    tools: dict[str, Tool] = {
        "file_search": FileSearchTool(file_manager),
        "file_read": FileReadTool(file_manager),
        "file_write": FileWriteTool(file_manager),
        "file_info": FileInfoTool(file_manager),
        "open_file": OpenFileTool(file_manager),
        "open_app": OpenAppTool(app_launcher),
        "open_url": OpenUrlTool(app_launcher),
        "list_apps": ListAppsTool(app_launcher),
        "run_code": RunCodeTool(file_manager),
        "run_shell": RunShellTool(file_manager),
        "browser_open": BrowserOpenTool(),
        "browser_text": BrowserTextTool(),
        "browser_html": BrowserHtmlTool(),
        "browser_js": BrowserJsTool(),
        "browser_click": BrowserClickTool(),
        "browser_wait": BrowserWaitTool(),
        "browser_screenshot": BrowserScreenshotTool(),
        "list_monitors": ListMonitorsTool(),
        "move_app": MoveAppTool(app_launcher),
        "close_app": CloseAppTool(app_launcher),
        "type_text": TypeTextTool(app_launcher),
        "press_key": PressKeyTool(),
        "mouse_click": MouseClickTool(),
        "mouse_scroll": MouseScrollTool(),
        "click_text": ClickTextTool(),
        "read_ui": ReadUiTool(),
        "screenshot": ScreenshotTool(file_manager, vision=OllamaVisionProvider()),
        "verify_screen": VerifyScreenTool(file_manager, verifier=get_vision_verifier()),
        "system_info": SystemInfoTool(),
        "system_config": SystemConfigTool(),
        "time": TimeTool(),
        "web_search": WebSearchTool(DuckDuckGoHtmlSearchProvider()),
    }
    if memory_service is not None:
        tools["memory_search"] = MemorySearchTool(memory_service)
        tools["memory_save"] = MemorySaveTool(memory_service)
        tools["memory_delete"] = MemoryDeleteTool(memory_service)
        tools["procedure_save"] = ProcedureSaveTool(memory_service)
        tools["procedure_run"] = ProcedureRunTool(memory_service)
    if task_service is not None:
        tools["task_create"] = TaskCreateTool(task_service)
        tools["task_execute"] = TaskExecuteTool(task_service)
        tools["task_list"] = TaskListTool(task_service)
        tools["task_register_path"] = TaskRegisterPathTool(task_service)
    if reminder_service is not None:
        tools["reminder_create"] = ReminderCreateTool(reminder_service)
        tools["reminder_list"] = ReminderListTool(reminder_service)
        tools["reminder_delete"] = ReminderDeleteTool(reminder_service)
    if calendar_service is not None:
        tools["calendar_create"] = CalendarCreateTool(calendar_service)
        tools["calendar_list"] = CalendarListTool(calendar_service)
        tools["calendar_delete"] = CalendarDeleteTool(calendar_service)
    return ToolRegistry(tools=tools)


def build_tool_registry(
    *,
    file_manager: FileManager | None = None,
    memory_service: MemoryService | None = None,
    task_service: Any | None = None,
    reminder_service: Any | None = None,
    calendar_service: Any | None = None,
) -> ToolRegistry:
    return build_default_tool_registry(
        file_manager=file_manager,
        memory_service=memory_service,
        task_service=task_service,
        reminder_service=reminder_service,
        calendar_service=calendar_service,
    )
