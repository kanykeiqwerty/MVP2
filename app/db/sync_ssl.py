"""
Подготовка DATABASE_URL и connect_args для psycopg2 (синхронный движок,
используется Celery-воркером).

В отличие от asyncpg, psycopg2 говорит на libpq напрямую и сам умеет
sslmode/sslrootcert — их не нужно вырезать из URL и не нужно превращать
в ssl.SSLContext, как в app/db/ssl.py для async-движка. Здесь ровно
обратная задача: убрать из URL driver-специфичный кусок (+asyncpg) и
передать SSL как обычные libpq connect_args.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.db.config import settings
from app.db.ssl import _LIBPQ_SSL_KEYS, _ssl_mode  # переиспользуем ту же логику выбора режима


def sync_database_url() -> str:
    """
    DATABASE_URL с драйвером psycopg2 вместо asyncpg.
    libpq SSL-параметры (sslmode, sslrootcert и т.п.) вырезаются из URL —
    они передаются явно через sync_connect_args(), где db_ssl имеет
    приоритет. Если оставить их в URL тоже, при переопределении через
    db_ssl получится дублирование параметра между URL и connect_args.
    """
    parts = urlsplit(settings.database_url)
    scheme = parts.scheme
    if scheme in ("postgresql", "postgres"):
        scheme = "postgresql+psycopg2"
    elif scheme.endswith("+asyncpg"):
        scheme = "postgresql+psycopg2"

    if not parts.query:
        return urlunsplit(parts._replace(scheme=scheme))

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _LIBPQ_SSL_KEYS
    ]
    return urlunsplit(parts._replace(scheme=scheme, query=urlencode(kept)))


def sync_connect_args() -> dict:
    """
    connect_args для create_engine (psycopg2).
    db_ssl/db_ssl_root_cert имеют приоритет над sslmode из самой строки
    подключения — так же, как и в async-версии (app/db/ssl.py).
    """
    mode = _ssl_mode()
    if not mode or mode == "disable":
        return {}

    args: dict = {"sslmode": mode}
    if mode in ("verify-ca", "verify-full") and settings.db_ssl_root_cert:
        args["sslrootcert"] = settings.db_ssl_root_cert
    return args