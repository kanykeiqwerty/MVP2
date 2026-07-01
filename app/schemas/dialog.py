import uuid
from datetime import datetime
from typing import Generic, TypeVar
 
from pydantic import BaseModel, ConfigDict, Field
 
from app.models.dialog import MessageRole, MessageStatus


T = TypeVar("T")
 
 
class Page(BaseModel, Generic[T]):
    """Универсальная обёртка для пагинированных списков."""
    total: int
    page: int
    page_size: int
    items: list[T]



class ConversationCreate(BaseModel):
    """title опционален — если не передан, backend может выставить его
    позже сам, например по первому сообщению в диалоге."""
    title: str | None = Field(default=None, max_length=500)
 
 
class ConversationUpdate(BaseModel):
    title: str = Field(..., max_length=500)
 
 
class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
 
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime
 
 
ConversationListResponse = Page[ConversationRead]
 
 
# ---------- Источники ответа ----------
 
class MessageSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
 
    id: uuid.UUID
    document_chunk_id: uuid.UUID
    document_id: uuid.UUID
    relevance_score: float | None = None
    rank: int
    created_at: datetime
 
 
class MessageSourceDetailed(MessageSourceRead):
    """Источник вместе с содержимым чанка и названием документа —
    удобно отдавать сразу на фронт, без дополнительных запросов."""
    document_title: str
    chunk_content: str
    chunk_page_number: int | None = None
    chunk_section_title: str | None = None
 
 
# ---------- Сообщения ----------
 
class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
 
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatus
    error_message: str | None = None
    created_at: datetime
    sources: list[MessageSourceRead] = []
 
 
class ConversationWithMessages(ConversationRead):
    """Диалог вместе со всей историей сообщений (для открытия чата)."""
    messages: list[MessageRead] = []
 
 
# ---------- Входная точка API для чата ----------
 
class ChatRequest(BaseModel):
    """
    Единственная input-схема для отправки сообщения.
    Если conversation_id не передан — backend создаёт новый диалог.
    Отдельной MessageCreate не заводим, чтобы не дублировать content.
    """
    conversation_id: uuid.UUID | None = None
    content: str = Field(..., min_length=1)
 
 
class ChatResponse(BaseModel):
    """Ответ ассистента вместе с использованными источниками."""
    conversation_id: uuid.UUID
    message: MessageRead
 
