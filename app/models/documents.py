
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    BigInteger,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.models.user import User

if TYPE_CHECKING:
    from app.models.dialog import MessageSource

from app.db.base import Base
 



class DocumentStatus(str, enum.Enum):
    queued = "queued"
    indexing = "indexing"
    ready = "ready"
    error = "error"
 
 
class DocumentFileType(str, enum.Enum):
    pdf = "pdf"
    docx = "docx"
    txt = "txt"



class Document(Base):
    __tablename__ = "documents"
 
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[DocumentFileType] = mapped_column(
        SAEnum(DocumentFileType, name="document_file_type"), nullable=False
    )
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, name="document_status"),
        nullable=False,
        default=DocumentStatus.queued,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())
    indexed_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
 
    uploader: Mapped["User"] = relationship()
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    status_logs: Mapped[list["DocumentStatusLog"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )




class DocumentStatusLog(Base):
    __tablename__ = "document_status_log"
 
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, name="document_status"), nullable=False
    )
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
 
    document: Mapped["Document"] = relationship(back_populates="status_logs")
 
 
# ---------- Чанки документов ----------
 
class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)
 
    # ПОСЛЕ подключения pgvector добавить:
    #   from pgvector.sqlalchemy import Vector
    #   embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    # и создать индекс HNSW/IVFFlat отдельной миграцией.
 
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
    Vector(1536),
    nullable=True,
)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    section_title: Mapped[str | None] = mapped_column(String(500))
    page_number: Mapped[int | None]
    token_count: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
 
    document: Mapped["Document"] = relationship(back_populates="chunks")
    sources: Mapped[list["MessageSource"]] = relationship(back_populates="document_chunk")
