from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler

from app.api.router import router
from app.core.limiter import limiter
from app.db.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserRole


async def _ensure_default_user() -> None:
    """
    Пока нет JWT-авторизации, диалоги ведутся от одного служебного юзера
    с фиксированным id (settings.DEFAULT_USER_ID). Заводим его при старте,
    если ещё не создан.
    """
    async with AsyncSessionLocal() as session:
        user = await session.get(User, settings.DEFAULT_USER_ID)
        if user is None:
            session.add(
                User(
                    id=settings.DEFAULT_USER_ID,
                    first_name="System",
                    last_name="Bot",
                    email="system@local",
                    hashed_password="not-set",
                    role=UserRole.admin,
                )
            )
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _ensure_default_user()
    yield


app = FastAPI(
    title="MVP2",
    description="API для MVP2",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(router)
