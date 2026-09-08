from __future__ import annotations

import platform
import sys
from typing import Any

from app.core.config import get_settings
from app.llm.router import LLMRouter
from app.tools.base import Tool, ToolPermission, ToolResult


class SystemInfoTool(Tool):
    name = "system_info"
    description = "Retorna informações básicas do sistema"
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "platform": platform.platform(),
                "python": sys.version,
                "machine": platform.machine(),
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}


class SystemConfigTool(Tool):
    name = "system_config"
    description = "Retorna a configuração atual do agente, incluindo modelo de IA, modo de execução e diretórios permitidos."
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        settings = get_settings()
        router_state = LLMRouter().describe_current()
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "app_name": settings.app_name,
                "app_env": settings.app_env,
                "llm_mode": settings.llm_mode,
                "provider_name": router_state.get("provider_name"),
                "model": router_state.get("model"),
                "base_url": router_state.get("base_url"),
                "allow_web": settings.allow_web,
                "allow_cloud_llm": settings.allow_cloud_llm,
                "allowed_directories": [str(path) for path in settings.allowed_directories],
                "memory_min_importance": settings.memory_min_importance,
                "rag_top_k": settings.rag_top_k,
                "agent_max_tool_iterations": settings.agent_max_tool_iterations,
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}
