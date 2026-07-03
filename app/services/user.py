import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserProfileUpdateRequest


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def update_profile(
        self,
        user_id: uuid.UUID,
        data: UserProfileUpdateRequest,
    ) -> User:
        user = await self.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        user.first_name = data.first_name
        user.last_name = data.last_name
        user.department = data.department
        user.position = data.position

        await self._db.commit()
        await self._db.refresh(user)
        return user

    async def create_user(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        role: str = "employee",
    ) -> User:
        user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            hashed_password=hash_password(password),
            role=role,
        )
        self._db.add(user)
        await self._db.commit()
        await self._db.refresh(user)
        return user

    async def update(
        self,
        user: User,
        first_name: str | None = None,
        last_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> User:
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active

        await self._db.commit()
        await self._db.refresh(user)
        return user

    async def soft_delete(self, user_id: uuid.UUID) -> None:
        user = await self.get_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")

        user.is_active = False
        await self._db.commit()

    async def get_all(self, limit: int = 50, offset: int = 0) -> tuple[list[User], int]:
        users_result = await self._db.execute(
            select(User).order_by(User.email).limit(limit).offset(offset)
        )
        users = list(users_result.scalars().all())

        total_result = await self._db.execute(select(func.count()).select_from(User))
        total = total_result.scalar() or 0

        return users, total
