import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import AdminUser, DBSession, ManagerUser
from app.core.exceptions import ConflictError, NotFoundError
from app.models.dialog import Conversation, Message, MessageFeedback, MessageRole
from app.models.documents import Document, DocumentStatus
from app.models.user import User
from app.schemas.admin import (
    AdminCreateUserRequest,
    AdminFeedbackItem,
    AdminFeedbackListResponse,
    AdminStatsResponse,
    AdminUpdateUserRequest,
    UserListItem,
    UserListResponse,
)
from app.services import dialog_service
from app.services.user import UserService

router = APIRouter(prefix="/admin", tags=["admin"])


# ─────────────────────────────────────────────────────────────────────────────
# Users CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=UserListResponse)
async def list_users(
    _: ManagerUser,
    db: DBSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserListResponse:
    users, total = await UserService(db).get_all(limit=limit, offset=offset)
    return UserListResponse(
        users=[UserListItem.model_validate(u) for u in users],
        total=total,
    )


@router.post("/users", response_model=UserListItem, status_code=201)
async def create_user(
    _: AdminUser,
    db: DBSession,
    body: AdminCreateUserRequest,
) -> UserListItem:
    svc = UserService(db)
    if await svc.get_by_email(body.email):
        raise ConflictError("Email already registered")
    user = await svc.create_user(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password=body.password,
        role=body.role,
    )
    return UserListItem.model_validate(user)


@router.get("/users/{user_id}", response_model=UserListItem)
async def get_user(
    user_id: uuid.UUID,
    _: AdminUser,
    db: DBSession,
) -> UserListItem:
    user = await UserService(db).get_by_id(user_id)
    if not user:
        raise NotFoundError("User not found")
    return UserListItem.model_validate(user)


@router.put("/users/{user_id}", response_model=UserListItem)
async def update_user(
    user_id: uuid.UUID,
    body: AdminUpdateUserRequest,
    _: AdminUser,
    db: DBSession,
) -> UserListItem:
    svc = UserService(db)
    user = await svc.get_by_id(user_id)
    if not user:
        raise NotFoundError("User not found")
    user = await svc.update(
        user,
        first_name=body.first_name,
        last_name=body.last_name,
        role=body.role,
        is_active=body.is_active,
    )
    return UserListItem.model_validate(user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    _: AdminUser,
    db: DBSession,
) -> None:
    svc = UserService(db)
    user = await svc.get_by_id(user_id)
    if not user:
        raise NotFoundError("User not found")
    await svc.update(user, is_active=False)


# ─────────────────────────────────────────────────────────────────────────────
# Feedback
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/feedback", response_model=AdminFeedbackListResponse)
async def list_feedback(
    _: AdminUser,
    db: DBSession,
    is_useful: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminFeedbackListResponse:
    records, total = await dialog_service.list_feedback(
        db, is_useful=is_useful, limit=limit, offset=offset
    )
    items = [
        AdminFeedbackItem(
            id=fb.id,
            message_id=fb.message_id,
            conversation_id=fb.message.conversation_id,
            is_useful=fb.is_useful,
            comment=fb.comment,
            created_at=fb.created_at,
            question=await dialog_service.get_preceding_question(db, fb.message),
            answer=fb.message.content,
            user_id=fb.user_id,
            user_name=fb.user.full_name,
            user_email=fb.user.email,
        )
        for fb in records
    ]
    return AdminFeedbackListResponse(items=items, total=total)


# ─────────────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=AdminStatsResponse)
async def get_usage_stats(
    _: AdminUser,
    db: DBSession,
) -> AdminStatsResponse:
    async def scalar(query) -> int:
        return (await db.execute(query)).scalar() or 0

    total_users = await scalar(select(func.count()).select_from(User))
    active_users = await scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )
    total_conversations = await scalar(select(func.count()).select_from(Conversation))
    total_questions = await scalar(
        select(func.count()).select_from(Message).where(Message.role == MessageRole.user)
    )
    total_documents = await scalar(select(func.count()).select_from(Document))
    documents_ready = await scalar(
        select(func.count()).select_from(Document).where(Document.status == DocumentStatus.ready)
    )
    total_feedback = await scalar(select(func.count()).select_from(MessageFeedback))
    useful_feedback = await scalar(
        select(func.count()).select_from(MessageFeedback).where(MessageFeedback.is_useful.is_(True))
    )
    not_useful_feedback = await scalar(
        select(func.count()).select_from(MessageFeedback).where(MessageFeedback.is_useful.is_(False))
    )

    return AdminStatsResponse(
        total_users=total_users,
        active_users=active_users,
        total_conversations=total_conversations,
        total_questions=total_questions,
        total_documents=total_documents,
        documents_ready=documents_ready,
        total_feedback=total_feedback,
        useful_feedback=useful_feedback,
        not_useful_feedback=not_useful_feedback,
    )
