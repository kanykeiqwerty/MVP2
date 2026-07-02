"""
Синхронный движок/сессия SQLAlchemy — только для Celery-воркера.

Celery-таски синхронные (prefork-модель воркера не рассчитана на asyncio),
поэтому им нужен отдельный движок на psycopg2, а не на asyncpg, который
использует основной async-движок (app/db/session.py). Пул сознательно
меньше: у воркера обычно 1 соединение на процесс, а не десятки
параллельных запросов, как у FastAPI.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.config import settings
from app.db.sync_ssl import sync_connect_args, sync_database_url

sync_engine = create_engine(
    sync_database_url(),
    echo=settings.app_env == "development",
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args=sync_connect_args(),
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    expire_on_commit=False,
    autoflush=False,
)


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """
    Аналог get_db() из app/db/session.py, но для синхронного кода.
    Использование в Celery-таске:

        with get_sync_db() as session:
            ...
    """
    session = SyncSessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()