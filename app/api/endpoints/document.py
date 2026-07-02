import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.documents import Document, DocumentFileType, DocumentStatus
from app.schemas.documents import (
    DocumentListResponse,
    DocumentRead,
    DocumentUpdate,
)
from app.services import documents_service
from app.services.documents_service import DocumentValidationError

router = APIRouter(prefix="/documents", tags=["Documents"])


async def _get_document_or_404(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await documents_service.get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")
    return document


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await documents_service.create_document(
            session=session,
            file=file,
            title=title,
            uploaded_by=None,  # TODO: заменить на current_user.id из JWT
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
    session: AsyncSession = Depends(get_db),
):
    return await _get_document_or_404(session, document_id)


@router.patch("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
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
    session: AsyncSession = Depends(get_db),
):
    document = await _get_document_or_404(session, document_id)
    await documents_service.delete_document(session, document)


# ---------- Переиндексация ----------


@router.post("/{document_id}/reindex", response_model=DocumentRead)
async def reindex_document(document_id: uuid.UUID, session: AsyncSession = Depends(get_db)):
    document = await _get_document_or_404(session, document_id)
    try:
        return await documents_service.requeue_for_reindex(session, document)
    except DocumentValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
