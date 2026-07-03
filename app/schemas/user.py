from datetime import date
import re
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.schemas.common import LocalDateTime


# class ManagerResponse(BaseModel):
#     model_config = ConfigDict(from_attributes=True)

#     id: UUID
#     first_name: str
#     last_name: str
#     email: EmailStr
#     position: str | None
#     department: str | None

#     @computed_field
#     @property
#     def full_name(self) -> str:
#         return f"{self.first_name} {self.last_name}"


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str
    
    
    email: EmailStr
    position: str | None
    department: str | None
    role: str                          # просмотр своей роли
    created_at: LocalDateTime
    last_login_at: LocalDateTime | None
    questions_count: int = 0



    @computed_field
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class UserProfileUpdateRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    department: str | None = None
    position: str | None = None

    

    