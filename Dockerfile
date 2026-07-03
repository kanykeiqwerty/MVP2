FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Корневой CA внешнего managed-Postgres (Timeweb Cloud) запечён в образ.
    # app/db/ssl.py читает его для sslmode=verify-full — отдельный секрет не нужен.
    DB_SSL_ROOT_CERT=/app/certs/root.crt

# Предпочитать IPv4 (IPv4-mapped) над IPv6: на нодах кластера нет рабочего IPv6,
# иначе httpx (OpenAI) и asyncpg (Timeweb DB) уходят в IPv6 -> Network unreachable.
RUN echo "precedence ::ffff:0:0/96  100" >> /etc/gai.conf

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads

EXPOSE 8000

# API. Контейнер worker в k8s переопределяет команду на celery (см. манифест 03-app.yaml).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
