from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.session import get_session
from app.runtime import build_agent

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    memory_created: bool = False


@router.post("")
async def chat(
    payload: ChatRequest,
    session=Depends(get_session),
) -> ChatResponse:
    agent = await build_agent(session)
    result = await agent.chat(
        payload.message,
        conversation_id=payload.conversation_id,
    )
    return ChatResponse(**result)