from slowapi import Limiter
from starlette.requests import Request


def _get_real_ip(request: Request) -> str:
    # Respect X-Forwarded-For set by nginx/Caddy reverse proxy
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_ip)
