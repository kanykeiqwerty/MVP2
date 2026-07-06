import uuid

from app.core.security import create_document_download_token
from app.db.config import settings
from app.models.documents import DocumentFileType


def document_download_url(
    document_id: uuid.UUID,
    *,
    file_type: DocumentFileType | None = None,
    page_number: int | None = None,
) -> str:
    """Абсолютная ссылка на скачивание документа.

    Содержит короткоживущий токен в query-строке: ссылку открывают напрямую
    (переход по ссылке, новая вкладка), а браузер при таком переходе не может
    приложить Authorization-заголовок, поэтому обычная Bearer-авторизация
    здесь не подходит.

    Для PDF с известным номером страницы добавляет #page=N — большинство
    браузерных/PDF.js-вьюеров открывают файл сразу на нужной странице,
    т.е. на том фрагменте, откуда пришёл ответ."""
    token = create_document_download_token(document_id)
    url = (
        f"{settings.base_url.rstrip('/')}{settings.api_v1_prefix}"
        f"/documents/{document_id}/download?token={token}"
    )
    if file_type == DocumentFileType.pdf and page_number is not None:
        url += f"#page={page_number}"
    return url
