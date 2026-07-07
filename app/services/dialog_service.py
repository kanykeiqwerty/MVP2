from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.urls import document_download_url, document_text_url
from app.db.config import settings
from app.models.dialog import (
    Conversation,
    Message,
    MessageFeedback,
    MessageRole,
    MessageSource,
    MessageStatus,
)
from app.models.documents import Document, DocumentChunk
from app.schemas.dialog import MessageRead, MessageSourceDocument, MessageSourceFragment
from app.services.llm import LLMError, generate_answer, generate_answer_stream
from app.services.retrieval import RetrievedChunk, search_chunks

NO_CONTEXT_ANSWER = "Не нашёл информации по этому вопросу в загруженных документах."
TITLE_MAX_LENGTH = 200


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


async def _get_recent_history(
    session: AsyncSession, conversation_id: uuid.UUID, limit: int
) -> list[dict[str, str]]:
    """Последние сообщения диалога (кроме текущего вопроса) в формате
    для OpenAI chat messages — чтобы уточняющие вопросы понимались в контексте."""
    query = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.status == MessageStatus.completed,
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = list((await session.execute(query)).scalars().all())
    rows.reverse()
    return [{"role": m.role.value, "content": m.content} for m in rows]


async def handle_chat_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID | None,
    content: str,
    user_id: uuid.UUID,
) -> Message:
    conversation = await _get_or_create_conversation(session, conversation_id, user_id)

    if conversation.title is None:
        conversation.title = content.strip()[:TITLE_MAX_LENGTH]

    history = await _get_recent_history(session, conversation.id, settings.CHAT_HISTORY_LIMIT)

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
        answer, used_sources = await generate_answer(
            content, [r.chunk.content for r in results], history=history
        )
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

    cited_results = _filter_cited_results(results, used_sources)
    for source in _build_sources(assistant_message.id, cited_results):
        session.add(source)

    await session.commit()
    await session.refresh(assistant_message)
    return assistant_message


def _filter_cited_results(
    results: list[RetrievedChunk], used_indices: set[int] | None
) -> list[RetrievedChunk]:
    """Оставляет только те найденные чанки, которые LLM реально указала в
    служебной строке "ИСТОЧНИКИ: ...", а не всё, что прошло порог similarity
    при поиске. used_indices=None — модель не проставила метку (не
    выполнила формат) — доверять фильтрации нельзя, возвращаем все чанки,
    как раньше."""
    if used_indices is None:
        return results
    return [r for i, r in enumerate(results, start=1) if i in used_indices]


def _build_sources(message_id: uuid.UUID, results: list[RetrievedChunk]) -> list[MessageSource]:
    return [
        MessageSource(
            message_id=message_id,
            document_chunk_id=result.chunk.id,
            document_id=result.chunk.document_id,
            relevance_score=result.similarity,
            rank=rank,
        )
        for rank, result in enumerate(results, start=1)
    ]


async def handle_chat_message_stream(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID | None,
    content: str,
    user_id: uuid.UUID,
) -> AsyncGenerator[tuple[str, dict], None]:
    """SSE-генератор для стриминга ответа ассистента.

    Отдаёт пары (event, data), которые endpoint форматирует в SSE:
    - "start": {conversation_id, message_id} — сразу после сохранения вопроса,
      чтобы фронт мог отрисовать сообщение пользователя и id для фидбека;
    - "delta": {content} — очередной кусочек текста ответа;
    - "done": сериализованный MessageRead — финальное сообщение с источниками;
    - "error": {message, retriable} — если LLM недоступен/упал по пути.
    """
    conversation = await _get_or_create_conversation(session, conversation_id, user_id)

    if conversation.title is None:
        conversation.title = content.strip()[:TITLE_MAX_LENGTH]

    history = await _get_recent_history(session, conversation.id, settings.CHAT_HISTORY_LIMIT)

    session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=content,
            status=MessageStatus.completed,
        )
    )

    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content="",
        status=MessageStatus.streaming,
    )
    session.add(assistant_message)
    await session.commit()
    await session.refresh(assistant_message)

    yield "start", {
        "conversation_id": str(conversation.id),
        "message_id": str(assistant_message.id),
    }

    results = await search_chunks(
        session,
        query=content,
        top_k=settings.RETRIEVAL_TOP_K,
        min_score=settings.RETRIEVAL_MIN_SCORE,
    )

    if not results:
        assistant_message.content = NO_CONTEXT_ANSWER
        assistant_message.status = MessageStatus.completed
        await session.commit()
        await session.refresh(assistant_message)

        yield "delta", {"content": NO_CONTEXT_ANSWER}
        message_read = await to_message_read(session, assistant_message)
        yield "done", message_read.model_dump(mode="json")
        return

    chunks: list[str] = []
    used_sources_holder: dict[str, set[int] | None] = {}
    try:
        async for delta in generate_answer_stream(
            content,
            [r.chunk.content for r in results],
            history=history,
            used_sources_out=used_sources_holder,
        ):
            chunks.append(delta)
            yield "delta", {"content": delta}
    except LLMError as exc:
        assistant_message.content = "".join(chunks)
        assistant_message.status = MessageStatus.error
        assistant_message.error_message = str(exc)
        await session.commit()
        yield "error", {"message": str(exc), "retriable": exc.retriable}
        return
    except (GeneratorExit, asyncio.CancelledError):
        # Клиент отключился (закрыл вкладку/оборвал соединение) до того, как
        # ответ был дописан целиком — сохраняем то, что уже успели
        # сгенерировать, вместо того чтобы бросать сообщение в статусе
        # "streaming" навсегда. Дальше не yield'им — GeneratorExit нельзя
        # "проглотить" продолжением генерации, можно только убрать за собой.
        assistant_message.content = "".join(chunks)
        assistant_message.status = MessageStatus.error
        assistant_message.error_message = "Соединение прервано до завершения ответа"
        await session.commit()
        raise

    assistant_message.content = "".join(chunks)
    assistant_message.status = MessageStatus.completed
    await session.flush()  # чтобы получить assistant_message.id для источников

    cited_results = _filter_cited_results(results, used_sources_holder.get("used"))
    for source in _build_sources(assistant_message.id, cited_results):
        session.add(source)

    await session.commit()
    await session.refresh(assistant_message)

    message_read = await to_message_read(session, assistant_message)
    yield "done", message_read.model_dump(mode="json")


async def _load_sources_detailed(
    session: AsyncSession, message_id: uuid.UUID
) -> list[MessageSourceDocument]:
    """
    Источники сообщения, сгруппированные по документу: одним запросом с
    джойнами (чтобы фронту не нужно было дальше ходить в /documents за
    каждым чанком отдельно), но на выходе — один объект на документ со
    списком фрагментов, а не плоский список чанков. Если несколько чанков
    одного документа попали в источники, это одна ссылка с несколькими
    фрагментами для подсветки, а не несколько дублирующихся ссылок на
    один и тот же файл.
    """
    query = (
        select(MessageSource, DocumentChunk, Document.title, Document.file_type)
        .join(DocumentChunk, DocumentChunk.id == MessageSource.document_chunk_id)
        .join(Document, Document.id == MessageSource.document_id)
        .where(MessageSource.message_id == message_id)
        .order_by(MessageSource.rank)
    )
    rows = (await session.execute(query)).all()

    groups: dict[uuid.UUID, MessageSourceDocument] = {}
    order: list[uuid.UUID] = []
    for source, chunk, title, file_type in rows:
        doc_id = source.document_id
        if doc_id not in groups:
            groups[doc_id] = MessageSourceDocument(
                document_id=doc_id,
                document_title=title,
                # Страница берётся у первого (= самого релевантного, т.к.
                # строки уже отсортированы по rank) фрагмента этого документа.
                document_download_url=document_download_url(
                    doc_id, file_type=file_type, page_number=chunk.page_number
                ),
                document_text_url=document_text_url(doc_id),
                fragments=[],
            )
            order.append(doc_id)
        groups[doc_id].fragments.append(
            MessageSourceFragment(
                id=source.id,
                document_chunk_id=source.document_chunk_id,
                relevance_score=source.relevance_score,
                rank=source.rank,
                chunk_content=chunk.content,
                chunk_index=chunk.chunk_index,
                chunk_page_number=chunk.page_number,
                chunk_section_title=chunk.section_title,
                chunk_start_offset=chunk.start_offset,
                chunk_end_offset=chunk.end_offset,
            )
        )

    return [groups[doc_id] for doc_id in order]


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


async def count_user_questions(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Сколько вопросов пользователь задал во всех своих диалогах — для профиля."""
    query = (
        select(func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id, Message.role == MessageRole.user)
    )
    return (await session.execute(query)).scalar() or 0


async def list_conversations(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[tuple[Conversation, int]], int]:
    """Диалоги пользователя с пагинацией, поиском по тексту (заголовок или
    содержимое сообщений) и фильтром по дате создания. Возвращает пары
    (диалог, количество сообщений в нём)."""
    message_count_subq = (
        select(func.count(Message.id))
        .where(Message.conversation_id == Conversation.id)
        .correlate(Conversation)
        .scalar_subquery()
    )

    query = select(Conversation, message_count_subq).where(Conversation.user_id == user_id)
    count_query = select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)

    if search:
        pattern = f"%{search}%"
        matching_conversation_ids = select(Message.conversation_id).where(
            Message.content.ilike(pattern)
        )
        condition = or_(
            Conversation.title.ilike(pattern),
            Conversation.id.in_(matching_conversation_ids),
        )
        query = query.where(condition)
        count_query = count_query.where(condition)

    if date_from is not None:
        query = query.where(func.date(Conversation.created_at) >= date_from)
        count_query = count_query.where(func.date(Conversation.created_at) >= date_from)
    if date_to is not None:
        query = query.where(func.date(Conversation.created_at) <= date_to)
        count_query = count_query.where(func.date(Conversation.created_at) <= date_to)

    query = (
        query.order_by(Conversation.updated_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )

    rows = [(row[0], row[1]) for row in (await session.execute(query)).all()]
    total = (await session.execute(count_query)).scalar() or 0
    return rows, total


async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


async def count_messages(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    query = select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
    return (await session.execute(query)).scalar_one()


async def get_messages_page(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    before_id: uuid.UUID | None,
    limit: int,
) -> tuple[list[Message], bool]:
    """Страница сообщений диалога для infinite scroll вверх: если before_id
    не задан — последние `limit` сообщений (открытие диалога), иначе —
    `limit` сообщений старше указанного. Возвращает их в хронологическом
    порядке и признак, есть ли ещё более старые сообщения."""
    query = select(Message).where(Message.conversation_id == conversation_id)

    if before_id is not None:
        before_message = await session.get(Message, before_id)
        if before_message is None:
            raise NotFoundError("Message not found")
        query = query.where(Message.created_at < before_message.created_at)

    query = query.order_by(Message.created_at.desc()).limit(limit + 1)
    rows = list((await session.execute(query)).scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    return rows, has_more


async def delete_conversation(session: AsyncSession, conversation: Conversation) -> None:
    await session.delete(conversation)
    await session.commit()


async def submit_feedback(
    session: AsyncSession,
    *,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    is_useful: bool,
    comment: str | None,
) -> MessageFeedback:
    """Ставит/обновляет оценку «полезно/не полезно» пользователя для сообщения."""
    message = await session.get(Message, message_id)
    if message is None:
        raise NotFoundError("Message not found")

    existing = await session.execute(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.user_id == user_id,
        )
    )
    feedback = existing.scalar_one_or_none()

    if feedback is not None:
        feedback.is_useful = is_useful
        feedback.comment = comment
    else:
        feedback = MessageFeedback(
            message_id=message_id,
            user_id=user_id,
            is_useful=is_useful,
            comment=comment,
        )
        session.add(feedback)

    await session.commit()
    await session.refresh(feedback)
    return feedback


async def list_feedback(
    session: AsyncSession,
    *,
    is_useful: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MessageFeedback], int]:
    """Фидбек пользователей по ответам ассистента — для просмотра администратором."""
    query = (
        select(MessageFeedback)
        .options(selectinload(MessageFeedback.message), selectinload(MessageFeedback.user))
        .order_by(MessageFeedback.created_at.desc())
    )
    count_query = select(func.count()).select_from(MessageFeedback)
    if is_useful is not None:
        query = query.where(MessageFeedback.is_useful == is_useful)
        count_query = count_query.where(MessageFeedback.is_useful == is_useful)

    query = query.limit(limit).offset(offset)
    records = list((await session.execute(query)).scalars().all())
    total = (await session.execute(count_query)).scalar() or 0
    return records, total


async def get_preceding_question(session: AsyncSession, message: Message) -> str | None:
    """Вопрос пользователя, на который был дан этот ответ ассистента."""
    query = (
        select(Message.content)
        .where(
            Message.conversation_id == message.conversation_id,
            Message.role == MessageRole.user,
            Message.created_at < message.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalar_one_or_none()
