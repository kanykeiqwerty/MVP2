import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

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
    MessagePage,
)
from app.services import dialog_service

router = APIRouter(prefix="/dialog", tags=["Dialog"])

DEFAULT_MESSAGES_LIMIT = 30
MAX_MESSAGES_LIMIT = 100


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


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    """
    То же самое, что POST /chat, но ответ ассистента отдаётся по SSE
    по мере генерации (event: start / delta / done / error) — для
    печатающегося вывода на фронте вместо ожидания полного ответа.
    """

    async def event_generator():
        generator = dialog_service.handle_chat_message_stream(
            session,
            conversation_id=payload.conversation_id,
            content=payload.content,
            user_id=current_user.id,
        )
        try:
            async for event, data in generator:
                if await request.is_disconnected():
                    break
                yield {"event": event, "data": json.dumps(data, ensure_ascii=False)}
        finally:
            # На break (клиент отключился) это доводит generator до конца:
            # бросает GeneratorExit в точке последнего yield, что даёт
            # handle_chat_message_stream сохранить partial content. На
            # обычное завершение — no-op, генератор уже исчерпан.
            await generator.aclose()

    return EventSourceResponse(event_generator())


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


async def _get_owned_conversation(
    session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> Conversation:
    conversation = await dialog_service.get_conversation(session, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Диалог не найден")
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    limit: int = Query(DEFAULT_MESSAGES_LIMIT, ge=1, le=MAX_MESSAGES_LIMIT),
):
    """Открытие диалога — метаданные вместе с последними `limit` сообщениями.
    Более старые подгружаются через GET /conversations/{id}/messages."""
    conversation = await _get_owned_conversation(session, conversation_id, current_user.id)

    total_messages = await dialog_service.count_messages(session, conversation_id)
    rows, has_more = await dialog_service.get_messages_page(
        session, conversation_id, before_id=None, limit=limit
    )
    messages = [await dialog_service.to_message_read(session, m) for m in rows]

    return ConversationWithMessages(
        id=conversation.id,
        user_id=conversation.user_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=total_messages,
        messages=messages,
        has_more_messages=has_more,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePage)
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
    before: uuid.UUID | None = Query(
        None, description="id самого старого уже загруженного сообщения — для подгрузки более старых"
    ),
    limit: int = Query(DEFAULT_MESSAGES_LIMIT, ge=1, le=MAX_MESSAGES_LIMIT),
):
    """Подгрузка более старых сообщений диалога при прокрутке вверх (infinite scroll)."""
    await _get_owned_conversation(session, conversation_id, current_user.id)

    rows, has_more = await dialog_service.get_messages_page(
        session, conversation_id, before_id=before, limit=limit
    )
    messages = [await dialog_service.to_message_read(session, m) for m in rows]
    return MessagePage(items=messages, has_more=has_more)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    conversation = await _get_owned_conversation(session, conversation_id, current_user.id)
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
