from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
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

app.include_router(router)
