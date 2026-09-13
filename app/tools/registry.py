from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.memory.service import MemoryService
from app.perception.vision import OllamaVisionProvider, get_vision_verifier
from app.skills.browser import (
    BrowserClickTool,
    BrowserHtmlTool,
    BrowserJsTool,
    BrowserOpenTool,
    BrowserScreenshotTool,
    BrowserTextTool,
    BrowserWaitTool,
)
from app.skills.calendar import CalendarCreateTool, CalendarDeleteTool, CalendarListTool
from app.skills.computer import (
    ApplicationLauncher,
    ClickTextTool,
    CloseAppTool,
    DetectCameraTool,
    ListAppsTool,
    ListMonitorsTool,
    MouseClickTool,
    MouseScrollTool,
    MoveAppTool,
    OpenAppTool,
    OpenFileTool,
    OpenUrlTool,
    PressKeyTool,
    ReadUiTool,
    ScreenshotTool,
    TypeTextTool,
    VerifyScreenTool,
    WindowsSearchTool,
)
from app.skills.documents import DocumentSearchTool
from app.skills.files import FileInfoTool, FileManager, FileReadTool, FileSearchTool, FileWriteTool
from app.skills.memory import (
    MemoryDeleteTool,
    MemorySaveTool,
    MemorySearchTool,
    ProcedureRunTool,
    ProcedureSaveTool,
)
from app.skills.reminders import ReminderCreateTool, ReminderDeleteTool, ReminderListTool
from app.skills.shell import RunCodeTool, RunShellTool
from app.skills.system import SystemConfigTool, SystemInfoTool, TimeTool
from app.skills.tasks import TaskCreateTool, TaskExecuteTool, TaskListTool, TaskRegisterPathTool
from app.skills.web import DuckDuckGoHtmlSearchProvider, WebSearchTool
from app.tools.base import Tool, ToolPermission, ToolResult
from app.tools.errors import ToolNotFoundError


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, Tool]

    def __post_init__(self) -> None:
        # Duplicidade de nome nunca é aceita silenciosamente (o sobrewriter
        # perde side effects — ex.: tool com serviço injetado).
        seen: set[str] = set()
        for name in self.tools:
            if name in seen:
                raise ValueError(f"tool duplicada no registry: {name}")
            seen.add(name)

    def list(self, permissions: set[ToolPermission] | None = None) -> list[Tool]:
        if permissions is None:
            return list(self.tools.values())
        return [tool for tool in self.tools.values() if tool.permission in permissions]

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise ToolNotFoundError(name)
        return self.tools[name]

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        return await self.get(name).execute(**kwargs)

    def schemas(self, permissions: set[ToolPermission] | None = None) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self.list(permissions)]


def build_default_tool_registry(
    file_manager: FileManager | None = None,
    memory_service: MemoryService | None = None,
    task_service: Any | None = None,
    reminder_service: Any | None = None,
    calendar_service: Any | None = None,
    document_indexer_factory: Any | None = None,
) -> ToolRegistry:
    file_manager = file_manager or FileManager()
    app_launcher = ApplicationLauncher()
    tools: dict[str, Tool] = {
        "file_search": FileSearchTool(file_manager), "file_read": FileReadTool(file_manager),
        "file_write": FileWriteTool(file_manager), "file_info": FileInfoTool(file_manager),
        "open_file": OpenFileTool(file_manager), "open_app": OpenAppTool(app_launcher),
        "open_url": OpenUrlTool(app_launcher), "list_apps": ListAppsTool(app_launcher),
        "run_code": RunCodeTool(file_manager), "run_shell": RunShellTool(file_manager),
        "detect_camera": DetectCameraTool(), "browser_open": BrowserOpenTool(),
        "browser_text": BrowserTextTool(), "browser_html": BrowserHtmlTool(),
        "browser_js": BrowserJsTool(), "browser_click": BrowserClickTool(),
        "browser_wait": BrowserWaitTool(), "browser_screenshot": BrowserScreenshotTool(),
        "list_monitors": ListMonitorsTool(), "move_app": MoveAppTool(app_launcher),
        "close_app": CloseAppTool(app_launcher), "type_text": TypeTextTool(app_launcher),
        "press_key": PressKeyTool(), "mouse_click": MouseClickTool(), "mouse_scroll": MouseScrollTool(),
        "click_text": ClickTextTool(), "read_ui": ReadUiTool(),
        "screenshot": ScreenshotTool(file_manager, vision=OllamaVisionProvider()),
        "verify_screen": VerifyScreenTool(file_manager, verifier=get_vision_verifier()),
        "windows_search": WindowsSearchTool(), "system_info": SystemInfoTool(),
        "system_config": SystemConfigTool(), "time": TimeTool(),
        "web_search": WebSearchTool(DuckDuckGoHtmlSearchProvider()),
    }
    if memory_service is not None:
        tools.update({
            "memory_search": MemorySearchTool(memory_service), "memory_save": MemorySaveTool(memory_service),
            "memory_delete": MemoryDeleteTool(memory_service), "procedure_save": ProcedureSaveTool(memory_service),
            "procedure_run": ProcedureRunTool(memory_service),
        })
    if task_service is not None:
        tools.update({"task_create": TaskCreateTool(task_service), "task_execute": TaskExecuteTool(task_service), "task_list": TaskListTool(task_service), "task_register_path": TaskRegisterPathTool(task_service)})
    if reminder_service is not None:
        tools.update({"reminder_create": ReminderCreateTool(reminder_service), "reminder_list": ReminderListTool(reminder_service), "reminder_delete": ReminderDeleteTool(reminder_service)})
    if calendar_service is not None:
        tools.update({"calendar_create": CalendarCreateTool(calendar_service), "calendar_list": CalendarListTool(calendar_service), "calendar_delete": CalendarDeleteTool(calendar_service)})
    if document_indexer_factory is not None:
        tools["document_search"] = DocumentSearchTool(document_indexer_factory)

    try:
        from app.macros.tools import (
            MacroCreateTool,
            MacroDeleteTool,
            MacroListTool,
            MacroRunTool,
            MacroSchedulesDeleteTool,
            MacroSchedulesEditTool,
            MacroSchedulesTool,
            MacroScheduleTool,
        )
        for cls in (MacroListTool, MacroRunTool, MacroCreateTool, MacroDeleteTool, MacroScheduleTool, MacroSchedulesTool, MacroSchedulesEditTool, MacroSchedulesDeleteTool):
            tools.setdefault(cls.name, cls())
    except ImportError:
        pass
    return ToolRegistry(tools=tools)


def build_tool_registry(**kwargs: Any) -> ToolRegistry:
    return build_default_tool_registry(**kwargs)
