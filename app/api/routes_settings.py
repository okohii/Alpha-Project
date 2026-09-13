from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.db.session import get_session
from app.tasks.service import ManagedPathRepository

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def settings(session=Depends(get_session)) -> dict:
    config = get_settings()
    from app.llm.router import LLMRouter

    router_state = LLMRouter().describe_current()
    records = await ManagedPathRepository(session).list()
    allowed_directories = [record.path for record in records if getattr(record, "is_allowed", 1)]
    if not allowed_directories:
        allowed_directories = [str(path) for path in config.allowed_directories]
    return {
        "app_name": config.app_name,
        "app_env": config.app_env,
        "llm_mode": config.llm_mode,
        "provider_name": router_state.get("provider_name"),
        "model": router_state.get("model"),
        "base_url": router_state.get("base_url"),
        "allow_web": config.allow_web,
        "stt_enabled": config.stt_enabled,
        "tts_enabled": config.tts_enabled,
        "memory_min_importance": config.memory_min_importance,
        "rag_top_k": config.rag_top_k,
        "agent_max_tool_iterations": config.agent_max_tool_iterations,
        "allowed_directories": allowed_directories,
        "allow_cloud_llm": config.allow_cloud_llm,
    }
