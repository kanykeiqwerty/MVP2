"""
Семантический поиск релевантных чанков документов по вопросу пользователя.

Ищем только среди документов со status=ready — по queued/indexing/error
чанков либо ещё нет, либо они не финальные.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import Document, DocumentChunk, DocumentStatus
from app.services.embedding import embed_texts


@dataclass
class RetrievedChunk:
    chunk: DocumentChunk
    similarity: float


async def search_chunks(
    session: AsyncSession,
    *,
    query: str,
    top_k: int,
    min_score: float,
) -> list[RetrievedChunk]:
    embeddings = await embed_texts([query])
    if not embeddings:
        return []
    query_embedding = embeddings[0]

    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(DocumentChunk, distance.label("distance"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.status == DocumentStatus.ready)
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()

    results: list[RetrievedChunk] = []
    for chunk, dist in rows:
        similarity = 1 - dist
        if similarity >= min_score:
            results.append(RetrievedChunk(chunk=chunk, similarity=similarity))
    return results
