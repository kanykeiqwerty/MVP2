from celery import Celery

from app.db.config import settings

celery_app = Celery(
    "kb_worker",
    broker=settings.REDIS_URL,
    # backend намеренно не задаём: статус индексации хранится и читается
    # из своей таблицы (Document.status / DocumentStatusLog), а не через
    # Celery AsyncResult — Redis используется только как брокер сообщений,
    # результаты задач в нём не накапливаются.
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,           # если воркер упадёт посреди задачи — она вернётся в очередь
    worker_prefetch_multiplier=1,  # не хватать пачками: индексация может быть долгой
    broker_connection_retry_on_startup=True,  # контейнер воркера может стартовать раньше Redis
    task_soft_time_limit=1500,     # 25 мин — мягкое исключение, таска может убраться сама
    task_time_limit=1800,          # 30 мин — жёсткое убийство процесса, если не отреагировала
    task_default_queue="indexing",
    task_routes={"app.workers.tasks.*": {"queue": "indexing"}},
)

celery_app.autodiscover_tasks(["app.workers"])