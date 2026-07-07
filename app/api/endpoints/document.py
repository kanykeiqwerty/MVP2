import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, ManagerUser, OptionalBearerCredentials
from app.core.security import decode_access_token, decode_document_download_token
from app.db.session import get_db
from app.models.documents import Document, DocumentFileType, DocumentStatus
from app.schemas.documents import (
    DocumentChunkListResponse,
    DocumentListResponse,
    DocumentRead,
    DocumentTextRead,
    DocumentUpdate,
)
from app.services import documents_service
from app.services.documents_service import DocumentValidationError
from app.services.parsing import ParsingError, extract_text
from app.services.storage import get_storage_backend
from app.services.user import UserService

DOCUMENT_MEDIA_TYPES = {
    DocumentFileType.pdf: "application/pdf",
    DocumentFileType.docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocumentFileType.txt: "text/plain",
}

router = APIRouter(prefix="/documents", tags=["Documents"])


async def _get_document_or_404(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await documents_service.get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    return document


def _verify_document_token(document_id: uuid.UUID, token: str | None) -> None:
    """Проверяет короткоживущий токен для ссылок, которые открывают напрямую
    (переход по URL) — браузер в этом случае не может приложить
    Authorization-заголовок, поэтому обычная Bearer-авторизация не подходит."""
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
    try:
        token_document_id = decode_document_download_token(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ссылка недействительна или истекла")
    if token_document_id != document_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ссылка недействительна или истекла")


async def _authorize_document_access(
    document_id: uuid.UUID,
    token: str | None,
    credentials: HTTPAuthorizationCredentials | None,
    session: AsyncSession,
) -> None:
    """Доступ разрешён обычным Bearer-токеном — как и у всего остального API,
    эндпоинт доступен в любой момент залогиненному пользователю — либо
    короткоживущим token из query-строки, нужным только для прямых переходов
    по ссылке-цитате из чата, где браузер не может приложить
    Authorization-заголовок."""
    if credentials is not None:
        try:
            payload = decode_access_token(credentials.credentials)
            user_id = uuid.UUID(payload["sub"])
        except (ValueError, KeyError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
        user = await UserService(session).get_by_id(user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
        return
    _verify_document_token(document_id, token)


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    user: ManagerUser,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await documents_service.create_document(
            session=session,
            file=file,
            title=title,
            uploaded_by=user.id,
        )
    except DocumentValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "",
    response_model=DocumentListResponse,
)
async def get_documents(
    _: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: DocumentStatus | None = Query(None, alias="status"),
    file_type: DocumentFileType | None = None,
    search: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    documents, total = await documents_service.list_documents(
        session=session,
        page=page,
        page_size=page_size,
        status=status_filter,
        file_type=file_type,
        search=search,
    )

    return DocumentListResponse(
        items=documents,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
)
async def get_document_by_id(
    document_id: uuid.UUID,
    _: CurrentUser,
    session: AsyncSession = Depends(get_db),
):
    return await _get_document_or_404(session, document_id)


@router.get(
    "/{document_id}/chunks",
    response_model=DocumentChunkListResponse,
)
async def get_document_chunks(
    document_id: uuid.UUID,
    _: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    await _get_document_or_404(session, document_id)
    chunks, total = await documents_service.list_chunks(
        session,
        document_id,
        page=page,
        page_size=page_size,
    )

    return DocumentChunkListResponse(
        items=chunks,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{document_id}/text",
    response_model=DocumentTextRead,
)
async def get_document_text(
    document_id: uuid.UUID,
    credentials: OptionalBearerCredentials,
    session: AsyncSession = Depends(get_db),
    token: str | None = Query(
        None,
        description=(
            "Нужен только при переходе по ссылке-цитате из чата (document_text_url), "
            "где токен уже вшит автоматически и вводить его вручную не требуется. "
            "При обычном обращении к API достаточно Bearer-авторизации."
        ),
    ),
):
    """Весь текст документа одним куском — извлекается из исходного файла
    заново (та же функция, что и при индексации), а не склеивается из
    чанков, потому что соседние чанки специально хранятся с overlap'ом.

    Это тот же текст, на который указывают start_offset/end_offset чанков
    в MessageSourceFragment — по ним фронт подсвечивает нужный фрагмент.

    Доступен как по обычной Bearer-авторизации (для просмотра в приложении
    в любой момент), так и по короткоживущему токену из query-строки — для
    прямых переходов по ссылке-цитате из чата (document_text_url), где
    браузер не может приложить Authorization-заголовок."""
    await _authorize_document_access(document_id, token, credentials, session)

    document = await _get_document_or_404(session, document_id)
    storage = get_storage_backend()
    path = storage.get_path(document.storage_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл документа не найден")

    try:
        text = extract_text(str(path), document.file_type)
    except ParsingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return DocumentTextRead(document_id=document.id, text=text)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    credentials: OptionalBearerCredentials,
    session: AsyncSession = Depends(get_db),
    token: str | None = Query(
        None,
        description=(
            "Нужен только при переходе по ссылке-цитате из чата (document_download_url), "
            "где токен уже вшит автоматически и вводить его вручную не требуется. "
            "При обычном обращении к API достаточно Bearer-авторизации."
        ),
    ),
):
    """Отдаёт файл документа для просмотра во вкладке (inline).

    Доступен как по обычной Bearer-авторизации (для просмотра в приложении
    в любой момент), так и по короткоживущему токену из query-строки,
    выданному на этот конкретный документ через document_download_url() —
    для прямых переходов по ссылке-цитате из чата, где браузер не может
    приложить Authorization-заголовок."""
    await _authorize_document_access(document_id, token, credentials, session)

    document = await _get_document_or_404(session, document_id)
    storage = get_storage_backend()
    path = storage.get_path(document.storage_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл документа не найден")
    return FileResponse(
        path=path,
        media_type=DOCUMENT_MEDIA_TYPES[document.file_type],
        filename=document.original_filename,
        content_disposition_type="inline",
    )


@router.patch("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    _: ManagerUser,
    session: AsyncSession = Depends(get_db),
):
    document = await _get_document_or_404(session, document_id)
    return await documents_service.update_title(session, document, payload.title)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_document(
    document_id: uuid.UUID,
    _: ManagerUser,
    session: AsyncSession = Depends(get_db),
):
    document = await _get_document_or_404(session, document_id)
    await documents_service.delete_document(session, document)


# ---------- Переиндексация ----------


@router.post("/{document_id}/reindex", response_model=DocumentRead)
async def reindex_document(document_id: uuid.UUID, _: ManagerUser, session: AsyncSession = Depends(get_db)):
    document = await _get_document_or_404(session, document_id)
    try:
        return await documents_service.requeue_for_reindex(session, document)
    except DocumentValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
