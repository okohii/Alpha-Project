from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.tools.base import Tool, ToolPermission, ToolResult


class SystemConfigTool(Tool):
    name = "system_config"
    description = (
        "Retorna configuração funcional do agente (modo, modelo, limites). "
        "Nunca expõe segredos, caminhos internos do filesystem ou allowlist."
    )
    permission = ToolPermission.read

    async def execute(self, **kwargs: Any) -> ToolResult:
        settings = get_settings()
        return ToolResult(
            name=self.name,
            success=True,
            data={
                "app_name": settings.app_name,
                "app_env": settings.app_env,
                "llm_mode": settings.llm_mode,
                "model": settings.ollama_model or settings.cloud_llm_model,
                "allow_web": settings.allow_web,
                "memory_min_importance": settings.memory_min_importance,
                "rag_top_k": settings.rag_top_k,
                "agent_max_tool_iterations": settings.agent_max_tool_iterations,
            },
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}