import uuid
import enum
from sqlalchemy import Boolean, ForeignKey, String, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import date, datetime
from sqlalchemy import Date, DateTime
from app.db.base import Base


class UserRole(str, enum.Enum):
    employee = "employee"      # Сотрудник
    manager = "manager"        # Руководитель
    admin = "admin"            # Администратор базы знаний
    superadmin = "superadmin"  # Суперадминистратор


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.employee, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    

    
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")  # type: ignore[name-defined]
    reset_codes: Mapped[list["PasswordResetCode"]] = relationship(back_populates="user", cascade="all, delete-orphan")  # type: ignore[name-defined]
    uploaded_documents: Mapped[list["Document"]] = relationship(back_populates="uploader")  # type: ignore[name-defined]
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")  # type: ignore[name-defined]
    feedback: Mapped[list["MessageFeedback"]] = relationship(back_populates="user", cascade="all, delete-orphan")  # type: ignore[name-defined]

    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"