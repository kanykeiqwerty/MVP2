import uuid

from app.db.config import settings
from app.models.documents import DocumentFileType


def document_download_url(
    document_id: uuid.UUID,
    *,
    file_type: DocumentFileType | None = None,
    page_number: int | None = None,
) -> str:
    """Абсолютная ссылка на скачивание документа.
    Для PDF с известным номером страницы добавляет #page=N — большинство
    браузерных/PDF.js-вьюеров открывают файл сразу на нужной странице,
    т.е. на том фрагменте, откуда пришёл ответ."""
    url = f"{settings.base_url.rstrip('/')}{settings.api_v1_prefix}/documents/{document_id}/download"
    if file_type == DocumentFileType.pdf and page_number is not None:
        url += f"#page={page_number}"
    return url
