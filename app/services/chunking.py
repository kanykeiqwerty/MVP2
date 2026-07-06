"""
Recursive-чанкинг.

Стратегия:
  1. Текст режется на абзацы (по пустой строке).
  2. Абзацы последовательно накапливаются в буфер, пока не превысят
     chunk_size символов — тогда буфер сбрасывается как чанк.
  3. Между соседними чанками сохраняется overlap символов (хвост
     предыдущего чанка), чтобы не терять контекст на границах. Хвост
     обрезается по границе слова, а не посередине.
  4. Если абзац похож на заголовок (короткая строка/markdown-заголовок/
     строка без завершающей точки), он становится текущим section_title
     для последующих чанков.
  5. page_number чанка определяется по page_breaks (см. parsing.py) —
     границам страниц PDF в том же тексте, который передан сюда.
  6. Абзац длиннее chunk_size режется жёстко, но по границе слова, а не
     произвольно посередине.

Все позиции (start_offset/end_offset чанка) — это реальные смещения в
символах в исходном тексте, поэтому content чанка всегда РОВНО равен
text[start_offset:end_offset] — это важно для фронта: он подсвечивает
именно этот диапазон в тексте, который отдаёт GET /documents/{id}/text
(это тот же текст, что передаётся сюда при индексации).

Это достаточно для MVP; семантический чанкинг (эмбеддинг-based split)
можно добавить позже как отдельную стратегию с тем же интерфейсом.
"""

import re
from dataclasses import dataclass

from app.services.parsing import PageBreak

_PARAGRAPH_SEP_RE = re.compile(r"\n\s*\n")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+.+$")
_CAPS_HEADING_RE = re.compile(r"^[A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9 \-.,:№]{3,90}$")

_HEADING_MAX_LEN = 80
_HEADING_MAX_WORDS = 8
_SENTENCE_ENDINGS = (".", "!", "?", ",", ";")


@dataclass
class Chunk:
    index: int
    content: str
    start_offset: int
    end_offset: int
    page_number: int | None
    section_title: str | None


def _looks_like_heading(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if not stripped or "\n" in stripped or len(stripped) > _HEADING_MAX_LEN:
        return False

    if _MD_HEADING_RE.match(stripped):
        return True
    if _CAPS_HEADING_RE.match(stripped):
        return True

    # Короткие строки-разделы вида "Общие положения", "Права работника" —
    # частый паттерн для заголовков в договорах/регламентах. Эвристика
    # грубая (может изредка принять короткое предложение за заголовок),
    # но для MVP это приемлемый компромисс: section_title — вспомогательное
    # поле, а не источник истины.
    if stripped.endswith(":"):
        return True
    if not stripped.endswith(_SENTENCE_ENDINGS) and len(stripped.split()) <= _HEADING_MAX_WORDS:
        return True

    return False


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Границы абзацев (start, end) в символах, разделённых пустой строкой,
    уже обрезанные от краевых пробелов/переводов строк."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for match in _PARAGRAPH_SEP_RE.finditer(text):
        spans.append((pos, match.start()))
        pos = match.end()
    spans.append((pos, len(text)))

    trimmed: list[tuple[int, int]] = []
    for start, end in spans:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            trimmed.append((start, end))
    return trimmed


def _page_at(page_breaks: list[PageBreak], offset: int) -> int | None:
    page: int | None = None
    for pb in page_breaks:
        if pb.offset <= offset:
            page = pb.page_number
        else:
            break
    return page


def recursive_chunk(
    text: str,
    page_breaks: list[PageBreak] | None = None,
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[Chunk]:
    if not text or not text.strip():
        return []

    page_breaks = page_breaks or []
    spans = _paragraph_spans(text)
    if not spans:
        return []

    chunks: list[Chunk] = []
    buffer_start: int | None = None
    buffer_end = 0
    buffer_page: int | None = None
    buffer_section: str | None = None
    current_section: str | None = None

    def flush() -> None:
        nonlocal buffer_start
        if buffer_start is not None and buffer_end > buffer_start:
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=text[buffer_start:buffer_end],
                    start_offset=buffer_start,
                    end_offset=buffer_end,
                    page_number=buffer_page,
                    section_title=buffer_section,
                )
            )
        buffer_start = None

    def overlap_start() -> int | None:
        """Начало overlap-хвоста последнего сброшенного чанка, обрезанное
        по границе слова, или None, если хвоста нет."""
        if not chunks or overlap <= 0:
            return None
        prev = chunks[-1]
        start = max(prev.start_offset, prev.end_offset - overlap)
        if start > prev.start_offset:
            space = text.find(" ", start, prev.end_offset)
            if space != -1:
                start = space + 1
        return start if start < prev.end_offset else None

    for p_start, p_end in spans:
        paragraph = text[p_start:p_end]
        page = _page_at(page_breaks, p_start)

        is_heading = _looks_like_heading(paragraph)
        if is_heading:
            current_section = paragraph

        if buffer_start is None:
            buffer_page = page
            buffer_section = current_section
        elif is_heading:
            # Заголовок встретился в уже непустом буфере (например, сразу после
            # жёсткого разреза длинного абзаца) — секцию всё равно обновляем.
            buffer_section = current_section

        candidate_start = p_start if buffer_start is None else buffer_start
        if p_end - candidate_start <= chunk_size:
            buffer_start = candidate_start
            buffer_end = p_end
            continue

        # Абзац целиком не влезает в текущий буфер — сбрасываем буфер
        flush()
        buffer_page = page
        buffer_section = current_section
        ov_start = overlap_start()

        if p_end - p_start <= chunk_size:
            buffer_start = ov_start if ov_start is not None else p_start
            buffer_end = p_end
            continue

        # Сам абзац длиннее chunk_size — режем его жёстко, но по словам
        buffer_start = ov_start if ov_start is not None else p_start
        buffer_end = buffer_start
        cursor = p_start
        while cursor < p_end:
            available = chunk_size - (buffer_end - buffer_start)
            if available <= 0:
                flush()
                buffer_page = page
                buffer_section = current_section
                ov_start = overlap_start()
                buffer_start = ov_start if ov_start is not None else cursor
                buffer_end = buffer_start
                continue

            if p_end - cursor <= available:
                piece_end = p_end
                next_cursor = p_end
            else:
                window_end = cursor + available
                cut = text.rfind(" ", cursor, window_end)
                if cut <= cursor:
                    cut = window_end
                piece_end = cut
                while piece_end > cursor and text[piece_end - 1] == " ":
                    piece_end -= 1
                next_cursor = cut
                while next_cursor < p_end and text[next_cursor] == " ":
                    next_cursor += 1
                if piece_end <= cursor:
                    piece_end = window_end
                    next_cursor = window_end

            buffer_end = piece_end
            cursor = next_cursor

            if cursor < p_end:
                flush()
                buffer_page = page
                buffer_section = current_section
                ov_start = overlap_start()
                buffer_start = ov_start if ov_start is not None else cursor
                buffer_end = buffer_start

    flush()
    return chunks
