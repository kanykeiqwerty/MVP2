import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.documents import DocumentFileType, DocumentStatus
from app.schemas.documents import (
    DocumentListResponse,
    DocumentRead,
)
from app.services.documents_service import (
    DocumentValidationError,
    create_document,
    delete_document,
    get_document,
    list_documents,
)

router = APIRouter(prefix="/documents", tags=["Documents"])


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
        document = await create_document(
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

    return document


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
    documents, total = await list_documents(
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
    document = await get_document(session, document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return document


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    document = await get_document(session, document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    await delete_document(session, document)