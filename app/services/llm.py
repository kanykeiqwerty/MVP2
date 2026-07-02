"""
Обёртка над OpenAI chat completions — генерация ответа на основе найденных
чанков документов (RAG). По аналогии с app/services/embedding.py: любая
ошибка обращения к OpenAI заворачивается в LLMError.
"""

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from app.db.config import settings

_async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

SYSTEM_PROMPT = (
    "Ты — ассистент базы знаний компании. Отвечай на вопрос пользователя, "
    "используя ТОЛЬКО информацию из контекста ниже. Если в контексте нет "
    "ответа на вопрос — так и скажи, не придумывай ответ. Отвечай на русском языке."
)


class LLMError(Exception):
    def __init__(self, message: str, *, retriable: bool = True) -> None:
        super().__init__(message)
        self.retriable = retriable


def _map_error(exc: Exception) -> LLMError:
    if isinstance(exc, AuthenticationError):
        return LLMError(
            "Ошибка аутентификации в OpenAI API — проверьте OPENAI_API_KEY",
            retriable=False,
        )
    if isinstance(exc, RateLimitError):
        return LLMError("Превышен лимит запросов к OpenAI API", retriable=True)
    if isinstance(exc, APIConnectionError):
        return LLMError("OpenAI API недоступен (проблема сети)", retriable=True)
    if isinstance(exc, APIStatusError):
        retriable = exc.status_code >= 500
        return LLMError(
            f"OpenAI API вернул ошибку {exc.status_code}: {exc.message}",
            retriable=retriable,
        )
    if isinstance(exc, APIError):
        return LLMError(f"Ошибка OpenAI API: {exc}", retriable=True)
    return LLMError(f"Непредвиденная ошибка при обращении к LLM: {exc}", retriable=True)


async def generate_answer(question: str, context_chunks: list[str]) -> str:
    context = "\n\n---\n\n".join(context_chunks)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Контекст:\n{context}\n\nВопрос: {question}"},
    ]
    try:
        response = await _async_client.chat.completions.create(
            model=settings.CHAT_MODEL,
            messages=messages,
            temperature=0.2,
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    return response.choices[0].message.content or ""
