from __future__ import annotations

import abc
from pathlib import Path

from app.db.config import settings


class StorageError(Exception):
    pass


class StorageBackend(abc.ABC):
    @abc.abstractmethod
    def save(self, *, filename: str, content: bytes, folder: str | None = None) -> str:
        """Сохраняет файл, возвращает storage_path для хранения в БД."""

    @abc.abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Удаляет файл. Не должен падать, если файла уже нет."""

    @abc.abstractmethod
    def get_path(self, storage_path: str) -> Path:
        """Возвращает локальный путь к файлу для стриминга/парсинга.
        Для S3-бэкенда — временная копия в tmp."""


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or settings.local_storage_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, storage_path: str) -> Path:
        path = (self.base_dir / storage_path).resolve()
        if self.base_dir.resolve() not in path.parents and path != self.base_dir.resolve():
            raise StorageError(f"Недопустимый storage_path: {storage_path}")
        return path

    def save(self, *, filename: str, content: bytes, folder: str | None = None) -> str:
        safe_name = Path(filename).name  # защита от path traversal
        relative_path = f"{folder}/{safe_name}" if folder else safe_name
        full_path = self._resolve(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        return relative_path

    async def delete(self, storage_path: str) -> None:
        path = self._resolve(storage_path)
        if path.exists():
            path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                pass

    def get_path(self, storage_path: str) -> Path:
        return self._resolve(storage_path)


def get_storage_backend() -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorageBackend()
    raise NotImplementedError(
        f"Storage backend '{settings.STORAGE_BACKEND}' пока не реализован. "
        "Добавьте класс, унаследованный от StorageBackend (например, S3StorageBackend)."
    )
