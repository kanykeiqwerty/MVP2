import uuid
from pydantic import BaseModel, EmailStr, Field, field_validator

PASSWORD_MIN_LENGTH = 6
PASSWORD_DESCRIPTION = (
    f"Минимум {PASSWORD_MIN_LENGTH} символов, "
    "минимум одна цифра и минимум одна заглавная буква"
)


def validate_password_strength(value: str) -> str:
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Пароль должен содержать минимум {PASSWORD_MIN_LENGTH} символов")
    if not any(ch.isdigit() for ch in value):
        raise ValueError("Пароль должен содержать минимум одну цифру")
    if not any(ch.isupper() for ch in value):
        raise ValueError("Пароль должен содержать минимум одну заглавную букву")
    return value


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(description=PASSWORD_DESCRIPTION)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
 
 
class LogoutRequest(BaseModel):
    refresh_token: str
    logout_all: bool = False  # True = выйти со всех устройств
 
 
class PasswordResetRequestBody(BaseModel):
    email: EmailStr
 
 
class PasswordResetConfirmBody(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(description=PASSWORD_DESCRIPTION)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)
 

class UserResponse(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    role: str

    model_config = {"from_attributes": True}