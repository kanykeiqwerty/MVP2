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
  5. Маркеры "--PAGE:N--" (расставленные parsing.py для PDF) не попадают
     в текст чанка, но обновляют текущий page_number.
  6. Абзац длиннее chunk_size режется жёстко, но по границе слова, а не
     произвольно посередине.

Это достаточно для MVP; семантический чанкинг (эмбеддинг-based split)
можно добавить позже как отдельную стратегию с тем же интерфейсом.
"""

import re
from dataclasses import dataclass

_PAGE_RE = re.compile(r"--PAGE:(\d+)--")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+.+$")
_CAPS_HEADING_RE = re.compile(r"^[A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9 \-.,:№]{3,90}$")

_HEADING_MAX_LEN = 80
_HEADING_MAX_WORDS = 8
_SENTENCE_ENDINGS = (".", "!", "?", ",", ";")


@dataclass
class Chunk:
    index: int
    content: str
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


def _split_on_word_boundary(text: str, max_len: int) -> tuple[str, str]:
    """(piece, remainder): piece не длиннее max_len, разрез по ближайшему пробелу слева."""
    if len(text) <= max_len:
        return text, ""
    cut = text.rfind(" ", 0, max_len)
    if cut <= 0:
        cut = max_len  # пробелов вообще нет (например, одно длинное слово) — режем жёстко
    return text[:cut].rstrip(), text[cut:].lstrip()


def _trim_to_word_boundary(text: str, overlap: int) -> str:
    """Хвост текста длиной ~overlap символов, обрезанный по границе слова."""
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    if len(tail) < len(text):
        space = tail.find(" ")
        if space != -1:
            tail = tail[space + 1 :]
    return tail


def recursive_chunk(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[Chunk]:
    if not text or not text.strip():
        return []

    paragraphs = re.split(r"\n\s*\n", text)

    chunks: list[Chunk] = []
    buffer = ""
    buffer_page: int | None = None
    buffer_section: str | None = None
    current_page: int | None = None
    current_section: str | None = None

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=buffer.strip(),
                    page_number=buffer_page,
                    section_title=buffer_section,
                )
            )
        buffer = ""

    def overlap_tail() -> str:
        return _trim_to_word_boundary(chunks[-1].content, overlap) if chunks else ""

    for raw_paragraph in paragraphs:
        paragraph = raw_paragraph

        page_match = _PAGE_RE.search(paragraph)
        if page_match:
            current_page = int(page_match.group(1))
            paragraph = _PAGE_RE.sub("", paragraph).strip()
            if not paragraph:
                continue

        is_heading = _looks_like_heading(paragraph)
        if is_heading:
            current_section = paragraph.strip()

        if not buffer:
            buffer_page = current_page
            buffer_section = current_section
        elif is_heading:
            # Заголовок встретился в уже непустом буфере (например, сразу после
            # жёсткого разреза длинного абзаца) — секцию всё равно обновляем.
            buffer_section = current_section

        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph

        if len(candidate) <= chunk_size:
            buffer = candidate
            continue

        # Абзац целиком не влезает в текущий буфер — сбрасываем буфер
        flush()
        buffer_page = current_page
        buffer_section = current_section
        tail = overlap_tail()

        if len(paragraph) <= chunk_size:
            buffer = f"{tail} {paragraph}" if tail else paragraph
            continue

        # Сам абзац длиннее chunk_size — режем его жёстко, но по словам
        buffer = tail
        remaining = paragraph
        while remaining:
            available = chunk_size - len(buffer) - (1 if buffer else 0)
            if available <= 0:
                flush()
                buffer_page = current_page
                buffer_section = current_section
                buffer = overlap_tail()
                continue

            piece, remaining = _split_on_word_boundary(remaining, available)
            buffer = f"{buffer} {piece}" if buffer else piece

            if remaining:
                flush()
                buffer_page = current_page
                buffer_section = current_section
                buffer = overlap_tail()

    flush()
    return chunks