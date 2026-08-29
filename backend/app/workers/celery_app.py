"""Celery application configuration."""

import sys

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "web_rag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    worker_concurrency=settings.celery_worker_concurrency,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=30,
    task_max_retries=3,
    # Periodic (celery beat) schedule for housekeeping jobs.
    beat_schedule={
        "cleanup-stuck-documents": {
            "task": "app.workers.tasks.cleanup_stuck_documents",
            "schedule": 600.0,  # every 10 minutes
        },
        "cleanup-expired-refresh-tokens": {
            "task": "app.workers.tasks.cleanup_expired_refresh_tokens",
            "schedule": 86400.0,  # every 24 hours
        },
    },
)

# Auto-discover tasks in app.workers.tasks so they are registered with the worker
celery_app.autodiscover_tasks(["app.workers"])

# On Windows, Celery's prefork pool uses spawn (no fork), and spawned child
# processes do NOT re-initialize the fast-trace optimization globals. This
# causes "ValueError: not enough values to unpack (expected 3, got 0)" in
# fast_trace_task. Use the solo pool on Windows to run tasks in-process.
if sys.platform == "win32":
    celery_app.conf.worker_pool = "solo"


@worker_process_init.connect
def init_worker(**kwargs: object) -> None:
    """Initialize worker process: setup DB connections, etc."""
    import logging

    logging.info("Worker process initializing...")


@worker_process_shutdown.connect
def shutdown_worker(**kwargs: object) -> None:
    """Cleanup on worker shutdown."""
    import logging

    logging.info("Worker process shutting down...")
