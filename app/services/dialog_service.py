from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.config import settings
from app.models.dialog import Conversation, Message, MessageRole, MessageSource, MessageStatus
from app.models.documents import Document, DocumentChunk
from app.schemas.dialog import MessageRead, MessageSourceDetailed
from app.services.llm import LLMError, generate_answer
from app.services.retrieval import search_chunks

NO_CONTEXT_ANSWER = "Не нашёл информации по этому вопросу в загруженных документах."


async def _get_or_create_conversation(
    session: AsyncSession, conversation_id: uuid.UUID | None, user_id: uuid.UUID
) -> Conversation:
    if conversation_id is not None:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is not None:
            return conversation

    conversation = Conversation(user_id=user_id)
    session.add(conversation)
    await session.flush()  # чтобы получить conversation.id для сообщений
    return conversation


async def handle_chat_message(
    session: AsyncSession, *, conversation_id: uuid.UUID | None, content: str
) -> Message:
    conversation = await _get_or_create_conversation(
        session, conversation_id, settings.DEFAULT_USER_ID
    )

    session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=content,
            status=MessageStatus.completed,
        )
    )
    await session.commit()

    results = await search_chunks(
        session,
        query=content,
        top_k=settings.RETRIEVAL_TOP_K,
        min_score=settings.RETRIEVAL_MIN_SCORE,
    )

    if not results:
        assistant_message = Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=NO_CONTEXT_ANSWER,
            status=MessageStatus.completed,
        )
        session.add(assistant_message)
        await session.commit()
        await session.refresh(assistant_message)
        return assistant_message

    try:
        answer = await generate_answer(content, [r.chunk.content for r in results])
    except LLMError as exc:
        assistant_message = Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content="",
            status=MessageStatus.error,
            error_message=str(exc),
        )
        session.add(assistant_message)
        await session.commit()
        await session.refresh(assistant_message)
        return assistant_message

    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content=answer,
        status=MessageStatus.completed,
    )
    session.add(assistant_message)
    await session.flush()  # чтобы получить assistant_message.id для источников

    for rank, result in enumerate(results, start=1):
        session.add(
            MessageSource(
                message_id=assistant_message.id,
                document_chunk_id=result.chunk.id,
                document_id=result.chunk.document_id,
                relevance_score=result.similarity,
                rank=rank,
            )
        )

    await session.commit()
    await session.refresh(assistant_message)
    return assistant_message


async def _load_sources_detailed(
    session: AsyncSession, message_id: uuid.UUID
) -> list[MessageSourceDetailed]:
    """
    Источники сообщения вместе с текстом чанка, страницей и названием
    документа — одним запросом с джойнами, чтобы фронту не нужно было
    дальше ходить в /documents за каждым чанком отдельно.
    """
    query = (
        select(MessageSource, DocumentChunk, Document.title)
        .join(DocumentChunk, DocumentChunk.id == MessageSource.document_chunk_id)
        .join(Document, Document.id == MessageSource.document_id)
        .where(MessageSource.message_id == message_id)
        .order_by(MessageSource.rank)
    )
    rows = (await session.execute(query)).all()
    return [
        MessageSourceDetailed(
            id=source.id,
            document_chunk_id=source.document_chunk_id,
            document_id=source.document_id,
            relevance_score=source.relevance_score,
            rank=source.rank,
            created_at=source.created_at,
            document_title=title,
            chunk_content=chunk.content,
            chunk_page_number=chunk.page_number,
            chunk_section_title=chunk.section_title,
        )
        for source, chunk, title in rows
    ]


async def to_message_read(session: AsyncSession, message: Message) -> MessageRead:
    sources = await _load_sources_detailed(session, message.id)
    return MessageRead(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        status=message.status,
        error_message=message.error_message,
        created_at=message.created_at,
        sources=sources,
    )


async def list_conversations(session: AsyncSession, user_id: uuid.UUID) -> list[Conversation]:
    query = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list((await session.execute(query)).scalars().all())


async def get_conversation_with_messages(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation | None:
    query = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    return (await session.execute(query)).scalar_one_or_none()
