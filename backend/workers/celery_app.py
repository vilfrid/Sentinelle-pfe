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
    result_expires=3600,       # discard task results from Redis after 1h
    task_default_retry_delay=60,
    task_max_retries=2,
)

# RGPD storage-limitation: purge old comments daily (requires `celery beat`)
celery_app.conf.beat_schedule = {
    "rgpd-purge-old-comments": {
        "task": "workers.tasks.purge_old_comments_task",
        "schedule": 24 * 60 * 60,   # once a day
    },
}
