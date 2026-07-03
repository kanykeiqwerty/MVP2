import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser
from app.db.session import get_db
from app.models.dialog import Conversation
from app.schemas.dialog import (
    ChatRequest,
    ChatResponse,
    ConversationListResponse,
    ConversationRead,
    ConversationWithMessages,
    MessageFeedbackRead,
    MessageFeedbackRequest,
)
from app.services import dialog_service

router = APIRouter(prefix="/dialog", tags=["Dialog"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    message = await dialog_service.handle_chat_message(
        session,
        conversation_id=payload.conversation_id,
        content=payload.content,
        user_id=current_user.id,
    )
    message_read = await dialog_service.to_message_read(session, message)
    return ChatResponse(conversation_id=message.conversation_id, message=message_read)


@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    rows, total = await dialog_service.list_conversations(
        session,
        current_user.id,
        page=page,
        page_size=page_size,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    items = [
        ConversationRead(
            id=conversation.id,
            user_id=conversation.user_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=message_count,
        )
        for conversation, message_count in rows
    ]
    return ConversationListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/conversations/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    conversation = await dialog_service.get_conversation_with_messages(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Диалог не найден")
    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Диалог не найден")

    messages = [await dialog_service.to_message_read(session, m) for m in conversation.messages]
    return ConversationWithMessages(
        id=conversation.id,
        user_id=conversation.user_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(messages),
        messages=messages,
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Диалог не найден")

    await dialog_service.delete_conversation(session, conversation)


@router.post("/messages/{message_id}/feedback", response_model=MessageFeedbackRead)
async def submit_message_feedback(
    message_id: uuid.UUID,
    body: MessageFeedbackRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    feedback = await dialog_service.submit_feedback(
        session,
        message_id=message_id,
        user_id=current_user.id,
        is_useful=body.is_useful,
        comment=body.comment,
    )
    return MessageFeedbackRead.model_validate(feedback)
