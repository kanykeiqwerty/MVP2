import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import settings
from app.db.session import get_db
from app.schemas.dialog import (
    ChatRequest,
    ChatResponse,
    ConversationRead,
    ConversationWithMessages,
)
from app.services import dialog_service

router = APIRouter(prefix="/dialog", tags=["Dialog"])


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, session: AsyncSession = Depends(get_db)):
    message = await dialog_service.handle_chat_message(
        session,
        conversation_id=payload.conversation_id,
        content=payload.content,
    )
    message_read = await dialog_service.to_message_read(session, message)
    return ChatResponse(conversation_id=message.conversation_id, message=message_read)


@router.get("/conversations", response_model=list[ConversationRead])
async def get_conversations(session: AsyncSession = Depends(get_db)):
    return await dialog_service.list_conversations(session, settings.DEFAULT_USER_ID)


@router.get("/conversations/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    conversation = await dialog_service.get_conversation_with_messages(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Диалог не найден")

    messages = [await dialog_service.to_message_read(session, m) for m in conversation.messages]
    return ConversationWithMessages(
        id=conversation.id,
        user_id=conversation.user_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=messages,
    )
