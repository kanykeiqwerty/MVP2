from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str
    # SSL для управляемого PostgreSQL (Timeweb): disable | require | verify-ca | verify-full
    # Если пусто — берётся sslmode из query-строки DATABASE_URL.
    db_ssl: str = ""
    db_ssl_root_cert: str = ""  # путь к root CA, напр. /app/certs/root.crt

   

    # Auth / JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 1 day
    refresh_token_expire_days: int = 30

    
    # Email (SMTP) — для отправки кода сброса пароля
    EMAIL_FROM: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    # Storage
    storage_backend: str = "local"
    local_storage_dir: Path = Path("uploads")

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Telegram alerts — forwards ERROR/WARNING logs to a chat (disabled if unset)
    telegram_bot_token: str = ""
    telegram_alert_chat_id: str = ""


    ALLOWED_EXTENSIONS: list[str] = [
        "pdf",
        "docx",
        "txt",
    ]

    MAX_UPLOAD_SIZE_MB: int = 20

    # --- Эмбеддинги ---
    OPENAI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    EMBEDDING_BATCH_SIZE: int = 64

    # --- Чанкинг ---
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150


settings = Settings()  # type: ignore[call-arg]
