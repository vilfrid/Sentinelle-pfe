from celery import Celery
from app.config import settings

celery_app = Celery(
    "sentinelle",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Africa/Tunis",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Retry failed tasks once after 60s
    task_default_retry_delay=60,
    task_max_retries=2,
)
