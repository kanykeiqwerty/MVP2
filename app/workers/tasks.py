import logging
from datetime import datetime, timezone

from app.workers.celery import celery_app
from celery.exceptions import SoftTimeLimitExceeded

from app.db.config import settings
from app.db.sync_session import SyncSessionLocal
from app.models.documents import Document, DocumentChunk, DocumentStatus, DocumentStatusLog
from app.services.chunking import recursive_chunk
from app.services.embedding import embed_texts_sync
from app.services.parsing import ParsingError, extract_text_with_pages
from app.services.storage import get_storage_backend


logger = logging.getLogger(__name__)


def _set_status(session, document: Document, status: DocumentStatus, message: str | None) -> None:
    document.status = status
    document.error_message = message if status == DocumentStatus.error else None
    if status == DocumentStatus.ready:
        document.indexed_at = datetime.now(timezone.utc)
    session.add(document)
    session.add(DocumentStatusLog(document_id=document.id, status=status, message=message))
    session.commit()


@celery_app.task(
    name="app.workers.tasks.index_document",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def index_document(self, document_id: str) -> None:
    """
    Полный пайплайн индексации одного документа.
    Идемпотентна: при повторном вызове (переиндексация) старые чанки удаляются.
    """
    session = SyncSessionLocal()
    try:
        document = session.get(Document, document_id)
        if document is None:
            logger.warning("index_document: документ %s не найден", document_id)
            return

        _set_status(session, document, DocumentStatus.indexing, "Индексация начата")

        try:
            storage = get_storage_backend()
            file_path = storage.get_path(document.storage_path)
            text, page_breaks = extract_text_with_pages(str(file_path), document.file_type)
            chunks = recursive_chunk(
                text,
                page_breaks,
                chunk_size=settings.CHUNK_SIZE,
                overlap=settings.CHUNK_OVERLAP,
            )
            if not chunks:
                raise ParsingError("Документ не содержит извлекаемого текста")

            # на случай переиндексации — чистим предыдущие чанки
            session.query(DocumentChunk).filter(
                DocumentChunk.document_id == document.id
            ).delete()
            session.commit()

            batch_size = settings.EMBEDDING_BATCH_SIZE
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                embeddings = embed_texts_sync([c.content for c in batch])
                for chunk, embedding in zip(batch, embeddings):
                    session.add(
                        DocumentChunk(
                            document_id=document.id,
                            chunk_index=chunk.index,
                            content=chunk.content,
                            embedding=embedding,
                            embedding_model=settings.EMBEDDING_MODEL,
                            section_title=chunk.section_title,
                            page_number=chunk.page_number,
                            start_offset=chunk.start_offset,
                            end_offset=chunk.end_offset,
                            token_count=max(1, len(chunk.content) // 4),
                        )
                    )
                session.commit()

            _set_status(
                session, document, DocumentStatus.ready, f"Готово: {len(chunks)} чанков"
            )

        except SoftTimeLimitExceeded:
            # За task_time_limit до жёсткого SIGKILL Celery кидает это исключение —
            # успеваем корректно зафиксировать ошибку вместо документа, "зависшего"
            # в статусе indexing навсегда. Не ретраим: тот же объём работы почти
            # наверняка снова упрётся в тот же лимит.
            logger.error("index_document: soft time limit exceeded для %s", document_id)
            session.rollback()
            document = session.get(Document, document_id)
            _set_status(
                session,
                document,
                DocumentStatus.error,
                "Индексация превысила лимит времени — документ слишком большой "
                "или сервис эмбеддингов отвечает слишком медленно",
            )

        except ParsingError as exc:
            # Ошибка парсинга не имеет смысла ретраить — файл сам по себе непригоден
            logger.warning("index_document: ошибка парсинга %s: %s", document_id, exc)
            session.rollback()
            document = session.get(Document, document_id)
            _set_status(session, document, DocumentStatus.error, str(exc))

        except Exception as exc:
            logger.exception("index_document: сбой при индексации %s", document_id)
            session.rollback()
            document = session.get(Document, document_id)
            _set_status(session, document, DocumentStatus.error, str(exc)[:2000])
            raise self.retry(exc=exc)

    finally:
        session.close()