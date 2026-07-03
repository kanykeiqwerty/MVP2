import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

# ───────────────────────────── Users ─────────────────────────────────────────
ALLOWED_ROLES = {"employee", "manager", "admin"}


class AdminCreateUserRequest(BaseModel):
    first_name: str = Field(min_length=2, max_length=100)
    last_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=6)
    role: str = Field(default="employee")

    def model_post_init(self, __context: object) -> None:
        if self.role not in ALLOWED_ROLES:
            raise ValueError(f"role must be one of {ALLOWED_ROLES}")


class AdminUpdateUserRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    role: str | None = None
    is_active: bool | None = None

    def model_post_init(self, __context: object) -> None:
        if self.role is not None and self.role not in ALLOWED_ROLES:
            raise ValueError(f"role must be one of {ALLOWED_ROLES}")


class UserListItem(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserListItem]
    total: int


# ───────────────────────────── Feedback ───────────────────────────────────

class AdminFeedbackItem(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    is_useful: bool
    comment: str | None
    created_at: datetime
    question: str | None
    answer: str
    user_id: uuid.UUID
    user_name: str
    user_email: str


class AdminFeedbackListResponse(BaseModel):
    items: list[AdminFeedbackItem]
    total: int


# ───────────────────────────── Statistics ─────────────────────────────────

class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_conversations: int
    total_questions: int
    total_documents: int
    documents_ready: int
    total_feedback: int
    useful_feedback: int
    not_useful_feedback: int
