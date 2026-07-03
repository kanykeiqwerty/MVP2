import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.user import UserService

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError):
        raise UnauthorizedError("Invalid token")

    user = await UserService(db).get_by_id(user_id)
    if not user:
        raise UnauthorizedError("User not found")
    if not user.is_active:
        raise UnauthorizedError("Account is disabled")
    return user


PRIVILEGED_ROLES = ("manager", "admin")


async def require_manager(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in PRIVILEGED_ROLES:
        raise ForbiddenError("Managers only")
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "admin":
        raise ForbiddenError("Admins only")
    return user


DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
ManagerUser = Annotated[User, Depends(require_manager)]
