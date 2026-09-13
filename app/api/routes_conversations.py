from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import Conversation
from app.db.session import get_session

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="New conversation")


@router.get("")
async def list_conversations(session=Depends(get_session)) -> list[dict]:
    conversations: list[object] = []
    try:
        if hasattr(session, "conversations"):
            conversations = list(session.conversations)
        else:
            query = select(Conversation)
            created_at_field = getattr(Conversation, "created_at", None)
            if created_at_field is not None and hasattr(created_at_field, "desc"):
                query = query.order_by(created_at_field.desc())
            result = await session.execute(query)
            conversations = list(result.scalars().all())
    except Exception:
        conversations = []
    return [
        {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
        }
        for conversation in conversations
    ]


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, session=Depends(get_session)) -> dict:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        return {"id": conversation_id, "found": False}
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


@router.post("")
async def create_conversation(
    payload: ConversationCreateRequest, session=Depends(get_session)
) -> dict:
    conversation = Conversation(title=payload.title)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
