"""

 
Соглашение по разделению схем:
  *Create   — то, что реально приходит от клиента в теле запроса
  *Read     — то, что отдаётся клиенту (полный набор полей)
  *Update   — то, что клиент может менять сам через API
  *Internal — то, что заполняет/меняет только backend (сервис индексации,
              обработчик загрузки файла и т.п.), наружу как input-схема
              не выставляется, используется только внутри сервисного слоя.
"""

import uuid
from datetime import datetime
from typing import Generic, TypeVar
 
from pydantic import BaseModel, ConfigDict, Field
 
from app.models.documents import (
    DocumentFileType,
    DocumentStatus,
    
)

T = TypeVar("T")
 
 
class Page(BaseModel, Generic[T]):
    """Универсальная обёртка для пагинированных списков."""
    total: int
    page: int
    page_size: int
    items: list[T]



class DocumentBase(BaseModel):
    """Общее поле, которое реально задаёт пользователь смыслово — название документа."""
    title: str = Field(..., max_length=500)
 
 
class DocumentCreate(BaseModel):
    """
    То, что реально приходит от клиента при POST /documents.
    Сам запрос — multipart/form-data (file=...), поэтому здесь только
    метаданные, которые клиент может/хочет указать явно.
    Если title не передан — backend возьмёт его из имени файла.
    title тут опционален, поэтому от DocumentBase не наследуемся.
    """
    title: str | None = Field(default=None, max_length=500)
 
 
class DocumentInternalCreate(DocumentBase):
    """
    Полный набор полей для создания записи Document в БД.
    Собирается backend'ом после приёма файла: original_filename и file_type
    выводятся из загруженного файла, file_size_bytes и storage_path —
    после сохранения файла в хранилище, uploaded_by — из текущего пользователя.
    Не является input-схемой API.
    """
    original_filename: str = Field(..., max_length=500)
    file_type: DocumentFileType
    file_size_bytes: int = Field(..., ge=0)
    storage_path: str = Field(..., max_length=1000)
    uploaded_by: uuid.UUID
 
 
class DocumentUpdate(DocumentBase):
    """Единственное, что клиент может поменять сам — название документа."""
    pass
 
 
class DocumentStatusUpdate(BaseModel):
    """
    Сервисное обновление статуса индексации.
    Выставляется индексатором/воркером, а не через публичный API.
    """
    status: DocumentStatus
    error_message: str | None = None
    indexed_at: datetime | None = None
 
 
class DocumentRead(DocumentBase):
    """
    Публичная версия документа для фронта.
    storage_path сюда намеренно не входит — это внутренний путь
    в хранилище (например, ключ в S3), клиенту он не нужен и
    отдавать его наружу — лишняя утечка деталей реализации.
    """
    model_config = ConfigDict(from_attributes=True)
 
    id: uuid.UUID
    original_filename: str
    file_type: DocumentFileType
    file_size_bytes: int
    status: DocumentStatus
    error_message: str | None = None
    uploaded_by: uuid.UUID
    uploaded_at: datetime
    indexed_at: datetime | None = None
    updated_at: datetime
 
 
class DocumentInternalRead(DocumentRead):
    """
    Полная версия документа для внутреннего использования
    (сервисный слой, индексатор, воркер скачивания файла) —
    включает storage_path. Наружу через API не отдаётся.
    """
    storage_path: str
 
 
class DocumentStatusLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
 
    id: int
    document_id: uuid.UUID
    status: DocumentStatus
    message: str | None = None
    created_at: datetime
 
 
class DocumentWithLogs(DocumentRead):
    """Документ вместе с историей смены статусов (для карточки/детального просмотра)."""
    status_logs: list[DocumentStatusLogRead] = []
 
 
DocumentListResponse = Page[DocumentRead]
 
 
# ---------- Чанки документов ----------
 
class DocumentChunkInternalCreate(BaseModel):
    """Создаётся исключительно пайплайном индексации, не через публичный API."""
    document_id: uuid.UUID
    chunk_index: int = Field(..., ge=0)
    content: str
    section_title: str | None = Field(default=None, max_length=500)
    page_number: int | None = None
    token_count: int | None = None
 
 
class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
 
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    section_title: str | None = None
    page_number: int | None = None
    token_count: int | None = None
    created_at: datetime
