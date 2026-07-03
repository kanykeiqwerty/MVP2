"""
app/models/auth_token.py

Модели для аутентификации — намеренно отдельно от models/session.py,
чтобы не конфликтовать с Session (чат-сессии со сценариями).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.schemas.common import now_local


class RefreshToken(Base, TimestampMixin):
    """Refresh-токен. Один ряд = одно устройство/браузер."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Храним SHA-256 хеш, не сам токен
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")  # type: ignore[name-defined]

    @property
    def is_expired(self) -> bool:
        return now_local() >= self.expires_at


class PasswordResetCode(Base, TimestampMixin):
    """Одноразовый 6-значный OTP для сброса пароля."""

    __tablename__ = "password_reset_codes"

    MAX_ATTEMPTS: int = 5

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="reset_codes")  # type: ignore[name-defined]

    @property
    def is_expired(self) -> bool:
        return now_local() >= self.expires_at

    @property
    def is_exhausted(self) -> bool:
        return self.attempts >= self.MAX_ATTEMPTS
