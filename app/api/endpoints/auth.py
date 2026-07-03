from fastapi import APIRouter, Request
from app.core.deps import CurrentUser, DBSession
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.limiter import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.schemas.auth import LoginRequest, LogoutRequest, PasswordResetConfirmBody, PasswordResetRequestBody, RefreshRequest, RegisterRequest, TokenResponse, UserResponse
from app.schemas.common import now_local
from app.services.auth_token import Auth_tokenService
from app.services.email import send_password_reset_code
from app.services.user import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


# Self-registration disabled — admin now creates users (see /admin/users), users log in with provided credentials.
# @router.post("/register", response_model=UserResponse, status_code=201)
# @limiter.limit("10/minute")
# async def register(request: Request, body: RegisterRequest, db: DBSession) -> UserResponse:
#     svc = UserService(db)
#     if await svc.get_by_email(body.email):
#         raise ConflictError("Email already registered")
#     user = await svc.create_user(body.name, body.email, body.password)
#     return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: DBSession) -> TokenResponse:
    user = await UserService(db).get_by_email(body.email)
    if not user or not verify_password(body.password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise UnauthorizedError("Account is disabled")
    
    user.last_login_at = now_local()
    await db.commit()

    token = create_access_token(subject=user.id)
    refresh_token = await Auth_tokenService(db).create_refresh_token(user.id)
    return TokenResponse(access_token=token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh(request: Request, body: RefreshRequest, db: DBSession) -> TokenResponse:
    """
    Обменивает refresh_token на новую пару токенов.
    Старый refresh_token при этом удаляется (rotation).
    """
    svc = Auth_tokenService(db)
    session = await svc.get_valid_session(body.refresh_token)
    if not session:
        raise UnauthorizedError("Invalid or expired refresh token")
 
    # Загружаем пользователя и проверяем что он ещё активен
    user = await UserService(db).get_by_id(session.user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("Account is disabled")
 
    # Rotation: старый токен удаляется, выдаём новый
    new_refresh = await svc.rotate_refresh_token(body.refresh_token, user.id)
    new_access = create_access_token(subject=user.id)
 
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)
 
 
@router.post("/logout", status_code=204)
async def logout(body: LogoutRequest, db: DBSession) -> None:
    """
    logout_all=False — выйти с текущего устройства.
    logout_all=True  — выйти со всех устройств.
    """
    svc = Auth_tokenService(db)
 
    if body.logout_all:
        session = await svc.get_valid_session(body.refresh_token)
        if session:
            await svc.delete_all_user_sessions(session.user_id)
    else:
        await svc.delete_session(body.refresh_token)
 


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)



# ── Password reset ────────────────────────────────────────────────────
 
@router.post("/password-reset/request", status_code=204)
@limiter.limit("3/minute")
async def password_reset_request(
    request: Request,
    body: PasswordResetRequestBody,
    db: DBSession,
) -> None:
    """
    Отправляет 6-значный OTP на email.
    Намеренно не раскрываем существует ли email — всегда 204.
    """
    user = await UserService(db).get_by_email(body.email)
    if user and user.is_active:
        code = await Auth_tokenService(db).create_reset_code(user.id)
        # В продакшене это лучше класть в очередь (Celery/ARQ),
        # но для простоты отправляем синхронно
        await send_password_reset_code(user.email, code)
 
 
@router.post("/password-reset/confirm", status_code=204)
@limiter.limit("5/minute")
async def password_reset_confirm(
    request: Request,
    body: PasswordResetConfirmBody,
    db: DBSession,
) -> None:
    """
    Проверяет OTP и устанавливает новый пароль.
    После успеха: код удаляется + все сессии инвалидируются.
    """
    user_svc = UserService(db)
    session_svc = Auth_tokenService(db)
 
    user = await user_svc.get_by_email(body.email)
    if not user or not user.is_active:
        raise UnauthorizedError("Invalid code")  # не раскрываем детали
 
    record = await session_svc.verify_reset_code(user.id, body.code)
    if not record:
        raise UnauthorizedError("Invalid or expired code")
 
    # Обновляем пароль
    user.hashed_password = hash_password(body.new_password)
    await db.commit()
 
    # Удаляем OTP и все активные сессии (форсируем повторный логин)
    await session_svc.delete_reset_code(user.id)
    await session_svc.delete_all_user_sessions(user.id)
