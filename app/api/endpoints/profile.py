from fastapi import APIRouter, status

from app.core.deps import CurrentUser, DBSession
from app.schemas.user import UserProfileResponse, UserProfileUpdateRequest
from app.services import dialog_service
from app.services.auth_token import Auth_tokenService
from app.services.user import UserService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserProfileResponse)
async def get_my_profile(current_user: CurrentUser, db: DBSession) -> UserProfileResponse:
    questions_count = await dialog_service.count_user_questions(db, current_user.id)
    profile = UserProfileResponse.model_validate(current_user)
    return profile.model_copy(update={"questions_count": questions_count})


@router.patch("", response_model=UserProfileResponse)
async def update_my_profile(
    body: UserProfileUpdateRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> UserProfileResponse:
    svc = UserService(db)
    updated_user = await svc.update_profile(current_user.id, body)
    return UserProfileResponse.model_validate(updated_user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_profile(
    current_user: CurrentUser,
    db: DBSession,
) -> None:
    """
    Мягкое удаление: деактивирует аккаунт, инвалидирует все сессии (токены).
    """
    svc = UserService(db)
    await svc.soft_delete(current_user.id)

    # Отзываем все refresh-токены — пользователь вылетит со всех устройств
    await Auth_tokenService(db).delete_all_user_sessions(current_user.id)
