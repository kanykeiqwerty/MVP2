"""
Обёртка над OpenAI embeddings (text-embedding-3-small).

sync-версия — для Celery-таски индексации, async — для API-слоя
(например, будущий semantic search по запросу пользователя).

Любая ошибка обращения к OpenAI (недоступен, истёк ключ, rate limit,
таймаут) заворачивается в EmbeddingError — вызывающий код (Celery-таска,
API-роутер) ловит один понятный тип, а не разбирается в деталях openai-sdk.
"""

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from app.db.config import settings

_async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
_sync_client = OpenAI(api_key=settings.OPENAI_API_KEY)


class EmbeddingError(Exception):
    """
    Единая ошибка сервиса эмбеддингов.
    retriable=True — имеет смысл повторить попытку позже (сеть, rate limit,
    временная недоступность OpenAI). retriable=False — повторять бессмысленно
    (невалидный ключ, некорректный запрос) — например, в Celery-таске такую
    ошибку не стоит заворачивать в self.retry().
    """

    def __init__(self, message: str, *, retriable: bool = True) -> None:
        super().__init__(message)
        self.retriable = retriable


def _map_error(exc: Exception) -> EmbeddingError:
    if isinstance(exc, AuthenticationError):
        return EmbeddingError(
            "Ошибка аутентификации в OpenAI API — проверьте OPENAI_API_KEY",
            retriable=False,
        )
    if isinstance(exc, RateLimitError):
        return EmbeddingError("Превышен лимит запросов к OpenAI API", retriable=True)
    if isinstance(exc, APIConnectionError):
        return EmbeddingError("OpenAI API недоступен (проблема сети)", retriable=True)
    if isinstance(exc, APIStatusError):
        # 4xx (кроме auth/rate limit выше) — как правило, невалидный запрос
        retriable = exc.status_code >= 500
        return EmbeddingError(
            f"OpenAI API вернул ошибку {exc.status_code}: {exc.message}",
            retriable=retriable,
        )
    if isinstance(exc, APIError):
        return EmbeddingError(f"Ошибка OpenAI API: {exc}", retriable=True)
    return EmbeddingError(f"Непредвиденная ошибка при получении эмбеддингов: {exc}", retriable=True)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Для использования из async-эндпоинтов (например, поиск по запросу)."""
    if not texts:
        return []
    try:
        response = await _async_client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=texts,
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    return [item.embedding for item in response.data]


def embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """Для использования из Celery-таски (синхронный воркер)."""
    if not texts:
        return []
    try:
        response = _sync_client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=texts,
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    return [item.embedding for item in response.data]