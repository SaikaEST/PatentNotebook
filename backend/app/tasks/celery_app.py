from celery import Celery
from kombu import Queue

from app.core.config import settings

celery_app = Celery(
    "patent_notebook",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.task_queues = (
    Queue("default"),
    Queue("ingest"),
    Queue("process"),
    Queue("ocr"),
    Queue("nlp"),
    Queue("export"),
)

celery_app.conf.task_routes = {
    "app.tasks.ingest.process_source": {"queue": "process"},
    "app.tasks.ingest.ocr_source": {"queue": "ocr"},
    "app.tasks.ingest.*": {"queue": "ingest"},
    "app.tasks.nlp.*": {"queue": "nlp"},
    "app.tasks.artifacts.*": {"queue": "nlp"},
    "app.tasks.exports.*": {"queue": "export"},
}

celery_app.conf.imports = (
    "app.tasks.ingest",
    "app.tasks.nlp",
    "app.tasks.artifacts",
    "app.tasks.exports",
)

celery_app.autodiscover_tasks(["app.tasks"])
