"""
Обёртка над OpenAI chat completions — генерация ответа на основе найденных
чанков документов (RAG). По аналогии с app/services/embedding.py: любая
ошибка обращения к OpenAI заворачивается в LLMError.
"""

import re
from collections.abc import AsyncGenerator

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
    "используя ТОЛЬКО информацию из пронумерованных источников ниже. Если ни "
    "один источник не отвечает на вопрос — так и скажи, не придумывай ответ. "
    "Отвечай на русском языке.\n\n"
    "В самом конце ответа, на новой строке, добавь строго в этом формате: "
    "\"ИСТОЧНИКИ: 1,3\" — через запятую номера ТОЛЬКО тех источников, "
    "информацию из которых ты реально использовал для ответа. Если не "
    "использовал ни одного — напиши \"ИСТОЧНИКИ: нет\". После этой строки "
    "больше ничего не пиши."
)

# Модель должна закончить ответ строкой вида "ИСТОЧНИКИ: 1,3" — по ней
# отбираем, какие из найденных чанков реально попадут в источники ответа
# (а не все, что прошли порог similarity при поиске).
_SOURCES_LINE_RE = re.compile(r"\n\s*ИСТОЧНИКИ:\s*(.*)\Z", re.IGNORECASE | re.DOTALL)
_NONE_TOKENS = {"нет", "-", "none", ""}


def _split_answer_and_used_sources(text: str) -> tuple[str, set[int] | None]:
    """Отделяет служебную строку "ИСТОЧНИКИ: ..." от текста ответа.

    Возвращает (текст_ответа, номера_источников). None вместо номеров
    означает, что модель не проставила метку (например, не следовала
    формату) — в этом случае доверять фильтрации нельзя, вызывающий код
    должен показать все найденные источники, как раньше.
    """
    match = _SOURCES_LINE_RE.search(text)
    if not match:
        return text.rstrip(), None

    raw = match.group(1).strip()
    if raw.lower() in _NONE_TOKENS:
        return text[: match.start()].rstrip(), set()

    numbers = {int(n) for n in re.findall(r"\d+", raw)}
    if not numbers:
        # Похоже на случайное совпадение (например, модель просто упомянула
        # слово "источники" где-то в тексте) — не режем ответ по нему.
        return text.rstrip(), None

    return text[: match.start()].rstrip(), numbers


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


def _build_messages(
    question: str,
    context_chunks: list[str],
    history: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    # Источники нумеруются, чтобы модель могла сослаться на них по номеру
    # в служебной строке "ИСТОЧНИКИ: ..." в конце ответа.
    context = "\n\n---\n\n".join(
        f"Источник {i}:\n{chunk}" for i, chunk in enumerate(context_chunks, start=1)
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": f"Контекст:\n{context}\n\nВопрос: {question}"})
    return messages


async def generate_answer(
    question: str,
    context_chunks: list[str],
    history: list[dict[str, str]] | None = None,
) -> tuple[str, set[int] | None]:
    """Возвращает (текст_ответа, номера_реально_использованных_источников).
    См. _split_answer_and_used_sources про смысл None."""
    messages = _build_messages(question, context_chunks, history)
    try:
        response = await _async_client.chat.completions.create(
            model=settings.CHAT_MODEL,
            messages=messages,
            temperature=0.2,
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    raw = response.choices[0].message.content or ""
    return _split_answer_and_used_sources(raw)


# Придерживаем этот "хвост" стрима, чтобы служебная строка "ИСТОЧНИКИ: ..."
# не успела утечь пользователю до того, как мы поймём, что это она (с
# запасом на "\nИСТОЧНИКИ: 1,2,3,4,5" при top_k=5).
_STREAM_LOOKAHEAD = 64


async def generate_answer_stream(
    question: str,
    context_chunks: list[str],
    history: list[dict[str, str]] | None = None,
    used_sources_out: dict[str, set[int] | None] | None = None,
) -> AsyncGenerator[str, None]:
    """Стримит ответ по кусочкам текста (delta) по мере поступления от OpenAI.

    Если передан used_sources_out, после завершения стрима туда кладётся
    used_sources_out["used"] — номера источников, которые модель реально
    использовала (см. _split_answer_and_used_sources); ключ выставляется,
    только если стрим завершился штатно (не при LLMError/отмене)."""
    messages = _build_messages(question, context_chunks, history)
    buffer = ""
    try:
        stream = await _async_client.chat.completions.create(
            model=settings.CHAT_MODEL,
            messages=messages,
            temperature=0.2,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if not delta:
                continue
            buffer += delta
            if len(buffer) > _STREAM_LOOKAHEAD:
                safe_len = len(buffer) - _STREAM_LOOKAHEAD
                to_yield, buffer = buffer[:safe_len], buffer[safe_len:]
                yield to_yield
    except Exception as exc:
        raise _map_error(exc) from exc

    answer, used = _split_answer_and_used_sources(buffer)
    if answer:
        yield answer
    if used_sources_out is not None:
        used_sources_out["used"] = used
