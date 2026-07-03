"""
app/services/auth_token.py
"""
import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_refresh_token, generate_reset_code, hash_token, refresh_token_expires_at
from app.models.auth_token import PasswordResetCode, RefreshToken
from app.schemas.common import now_local

RESET_CODE_TTL = timedelta(minutes=10)


class Auth_tokenService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Refresh tokens ────────────────────────────────────────────────

    async def create_refresh_token(self, user_id: uuid.UUID) -> str:
        """Создаёт refresh-токен, сохраняет хеш в БД, возвращает plain токен."""
        raw, token_hash = generate_refresh_token()
        session = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=refresh_token_expires_at(),
        )
        self._db.add(session)
        await self._db.flush()
        await self._db.commit()
        return raw

    async def get_valid_session(self, token: str) -> RefreshToken | None:
        """Возвращает сессию если токен существует и не просрочен."""
        result = await self._db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
        )
        session = result.scalar_one_or_none()
        if session is None or session.is_expired:
            return None
        return session

    async def rotate_refresh_token(self, old_token: str, user_id: uuid.UUID) -> str:
        """
        Refresh token rotation:
        удаляет старый токен и создаёт новый.
        Так скомпрометированный токен нельзя использовать дважды.
        """
        await self._db.execute(
            delete(RefreshToken).where(RefreshToken.token_hash == hash_token(old_token))
        )
        return await self.create_refresh_token(user_id)

    async def delete_session(self, token: str) -> None:
        """Logout с одного устройства."""
        await self._db.execute(
            delete(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
        )
        await self._db.commit()

    async def delete_all_user_sessions(self, user_id: uuid.UUID) -> None:
        """Logout со всех устройств."""
        await self._db.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user_id)
        )
        await self._db.commit()

    # ── Password reset OTP ────────────────────────────────────────────

    async def create_reset_code(self, user_id: uuid.UUID) -> str:
        """
        Генерирует 6-значный OTP.
        Старые коды пользователя удаляются — активен только последний.
        """
        await self._db.execute(
            delete(PasswordResetCode).where(PasswordResetCode.user_id == user_id)
        )
        code, code_hash = generate_reset_code()
        record = PasswordResetCode(
            user_id=user_id,
            code_hash=code_hash,
            expires_at=now_local() + RESET_CODE_TTL,
        )
        self._db.add(record)
        await self._db.flush()
        await self._db.commit()
        return code

    async def verify_reset_code(self, user_id: uuid.UUID, code: str) -> PasswordResetCode | None:
        """
        Проверяет OTP. При неверном коде увеличивает счётчик попыток.
        После 5 неудач код блокируется.
        """
        result = await self._db.execute(
            select(PasswordResetCode).where(PasswordResetCode.user_id == user_id)
        )
        record = result.scalar_one_or_none()

        if record is None or record.is_expired or record.is_exhausted:
            return None

        if record.code_hash != hash_token(code):
            record.attempts += 1
            await self._db.commit()
            return None

        return record

    async def delete_reset_code(self, user_id: uuid.UUID) -> None:
        await self._db.execute(
            delete(PasswordResetCode).where(PasswordResetCode.user_id == user_id)
        )
        await self._db.commit()