from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.config import settings
from app.models.documents import Document, DocumentChunk, DocumentFileType, DocumentStatus, DocumentStatusLog
from app.services.storage import StorageError, get_storage_backend
from app.workers.tasks import index_document

ALLOWED_EXTENSIONS = set(settings.ALLOWED_EXTENSIONS)
MAX_UPLOAD_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


class DocumentValidationError(Exception):
    pass


def _detect_file_type(filename: str | None) -> DocumentFileType:
    if not filename:
        raise DocumentValidationError("Имя файла не указано")
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentValidationError(
            f"Недопустимый тип файла '.{ext}'. Разрешены: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return DocumentFileType(ext)


async def create_document(
    session: AsyncSession,
    *,
    file: UploadFile,
    title: str | None,
    uploaded_by: uuid.UUID | None,
) -> Document:
    file_type = _detect_file_type(file.filename)

    content = await file.read()
    if not content:
        raise DocumentValidationError("Файл пуст")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DocumentValidationError(
            f"Файл превышает максимальный размер {settings.MAX_UPLOAD_SIZE_MB} МБ"
        )

    document = Document(
        title=title or Path(file.filename).stem,  # type: ignore[arg-type]
        original_filename=file.filename,  # type: ignore[arg-type]
        file_type=file_type,
        file_size_bytes=len(content),
        storage_path="",  # временно, заполним после сохранения файла
        status=DocumentStatus.queued,
        uploaded_by=uploaded_by,
    )
    session.add(document)
    await session.flush()  # чтобы получить document.id для storage-ключа

    storage = get_storage_backend()
    document.storage_path = storage.save(
        filename=f"{document.id}.{file_type.value}",
        content=content,
        folder=str(document.id),
    )

    session.add(DocumentStatusLog(document_id=document.id, status=DocumentStatus.queued))
    await session.commit()
    await session.refresh(document)

    index_document.delay(str(document.id))
    return document


async def list_documents(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    status: DocumentStatus | None = None,
    file_type: DocumentFileType | None = None,
    search: str | None = None,
) -> tuple[list[Document], int]:
    query = select(Document)
    count_query = select(func.count()).select_from(Document)

    if status is not None:
        query = query.where(Document.status == status)
        count_query = count_query.where(Document.status == status)
    if file_type is not None:
        query = query.where(Document.file_type == file_type)
        count_query = count_query.where(Document.file_type == file_type)
    if search:
        pattern = f"%{search}%"
        query = query.where(Document.title.ilike(pattern))
        count_query = count_query.where(Document.title.ilike(pattern))

    total = (await session.execute(count_query)).scalar_one()

    query = query.order_by(Document.uploaded_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = (await session.execute(query)).scalars().all()

    return list(items), total


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return await session.get(Document, document_id)


async def list_chunks(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
) -> tuple[list[DocumentChunk], int]:
    count_query = select(func.count()).select_from(DocumentChunk).where(
        DocumentChunk.document_id == document_id
    )
    total = (await session.execute(count_query)).scalar_one()

    query = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = (await session.execute(query)).scalars().all()

    return list(items), total


async def get_document_with_logs(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    query = (
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.status_logs))
    )
    return (await session.execute(query)).scalar_one_or_none()


async def update_title(session: AsyncSession, document: Document, title: str) -> Document:
    document.title = title
    await session.commit()
    await session.refresh(document)
    return document


async def delete_document(session: AsyncSession, document: Document) -> None:
    storage = get_storage_backend()
    try:
        await storage.delete(document.storage_path)
    except StorageError:
        pass  # файла уже нет в storage — не блокируем удаление записи в БД
    await session.delete(document)  # cascade="all, delete-orphan" удалит chunks и status_logs
    await session.commit()


async def requeue_for_reindex(session: AsyncSession, document: Document) -> Document:
    if document.status == DocumentStatus.indexing:
        raise DocumentValidationError("Документ уже находится в процессе индексации")

    document.status = DocumentStatus.queued
    document.error_message = None
    session.add(document)
    session.add(
        DocumentStatusLog(
            document_id=document.id,
            status=DocumentStatus.queued,
            message="Поставлен на переиндексацию",
        )
    )
    await session.commit()
    await session.refresh(document)

    index_document.delay(str(document.id))
    return document
