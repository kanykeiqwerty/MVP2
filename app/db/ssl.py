"""Подготовка DATABASE_URL и SSL-контекста для asyncpg.

asyncpg не понимает libpq-параметры (`sslmode`, `sslrootcert` и т.п.) в строке
подключения, поэтому их нужно вырезать из URL, а SSL передавать отдельным
аргументом `connect_args={"ssl": <SSLContext>}`.

Управляемый PostgreSQL Timeweb требует TLS (`verify-full`) с публичным root CA
(https://st.timeweb.com/cloud-static/ca.crt), который запекается в образ.
"""
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.db.config import settings

# libpq-параметры, которые asyncpg не принимает и которые надо убрать из URL.
_LIBPQ_SSL_KEYS = {"sslmode", "sslrootcert", "sslcert", "sslkey", "ssl"}


def database_url() -> str:
    """DATABASE_URL без libpq-параметров SSL (их asyncpg не парсит)."""
    parts = urlsplit(settings.database_url)
    if not parts.query:
        return settings.database_url
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _LIBPQ_SSL_KEYS
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def _ssl_mode() -> str:
    mode = (settings.db_ssl or "").strip().lower()
    if mode:
        return mode
    # fallback: sslmode из query-строки DATABASE_URL
    query = dict(parse_qsl(urlsplit(settings.database_url).query))
    return query.get("sslmode", "").strip().lower()


def ssl_context() -> ssl.SSLContext | None:
    """SSLContext по db_ssl / sslmode, либо None если SSL не нужен."""
    mode = _ssl_mode()
    if mode in ("", "disable"):
        return None
    if mode in ("require", "prefer", "allow"):
        # Шифруем, но не проверяем сертификат сервера.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    # verify-ca / verify-full — проверяем сертификат по root CA.
    ctx = ssl.create_default_context(cafile=settings.db_ssl_root_cert or None)
    if mode == "verify-ca":
        ctx.check_hostname = False
    return ctx


def connect_args() -> dict:
    """connect_args для create_async_engine."""
    ctx = ssl_context()
    return {"ssl": ctx} if ctx is not None else {}
