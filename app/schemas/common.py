from datetime import datetime, timedelta, timezone
from typing import Annotated

from pydantic import PlainSerializer

# UTC+6 — Asia/Bishkek, no DST
LOCAL_TZ = timezone(timedelta(hours=6))


def now_local() -> datetime:
    """Текущее время в Бишкеке. Использовать везде вместо datetime.now(UTC)."""
    return datetime.now(LOCAL_TZ)


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(LOCAL_TZ)


def duration_seconds(start: datetime, end: datetime | None) -> int | None:
    if end is None:
        return None
    return int((end - start).total_seconds())


# Serializes any datetime field as +06:00 on output, regardless of how it was stored/validated.
LocalDateTime = Annotated[datetime, PlainSerializer(to_local, return_type=datetime)]
