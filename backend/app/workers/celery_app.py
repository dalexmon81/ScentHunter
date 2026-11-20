"""Celery configuration for catalog-first background jobs."""
from __future__ import annotations
import os
from urllib.parse import urlparse
from celery import Celery
from kombu import Queue

BROKER_URL = os.environ.get("SCENTHUNTER_REDIS_URL", "").strip() or None
RESULT_BACKEND = os.environ.get("SCENTHUNTER_CELERY_RESULT_BACKEND") or None
QUEUES = (
    Queue("discovery", routing_key="discovery"),
    Queue("offers", routing_key="offers"),
    Queue("normalization", routing_key="normalization"),
    Queue("matching", routing_key="matching"),
    Queue("validation", routing_key="validation"),
    Queue("refresh", routing_key="refresh"),
    Queue("dead_letter", routing_key="dead_letter"),
)
TASK_ROUTES = {
    "app.workers.tasks.discover_store_products": {"queue": "discovery"},
    "app.workers.tasks.fetch_store_offers": {"queue": "offers"},
    "app.workers.tasks.normalize_offer": {"queue": "normalization"},
    "app.workers.tasks.match_offer_to_variant": {"queue": "matching"},
    "app.workers.tasks.validate_offer": {"queue": "validation"},
    "app.workers.tasks.refresh_price_and_stock": {"queue": "refresh"},
    "app.workers.tasks.quarantine_failed_connector": {"queue": "dead_letter"},
    "app.workers.tasks.reprocess_failed_offers": {"queue": "dead_letter"},
    "app.workers.tasks.worker_health_probe": {"queue": "offers"},
}
celery_app = Celery("scenthunter_catalog", broker=BROKER_URL, backend=RESULT_BACKEND, include=["app.workers.tasks"])
celery_app.conf.update(
    task_queues=QUEUES, task_routes=TASK_ROUTES, task_default_queue="offers",
    task_default_delivery_mode="persistent", task_serializer="json",
    result_serializer="json", accept_content=["json"], task_acks_late=True,
    task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    task_track_started=True, task_send_sent_event=True,
    broker_connection_retry_on_startup=True, task_publish_retry=True,
    task_publish_retry_policy={"max_retries": 5, "interval_start": 0.2, "interval_step": 0.5, "interval_max": 3},
    task_annotations={"*": {"max_retries": 5, "retry_backoff": True, "retry_backoff_max": 900, "retry_jitter": True}},
    task_create_missing_queues=False, broker_transport_options={"visibility_timeout": 3600},
)
def queue_is_configured(environ=None) -> bool:
    env = os.environ if environ is None else environ
    value = str(env.get("SCENTHUNTER_REDIS_URL", "")).strip()
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"redis", "rediss"} and bool(parsed.hostname) and parsed.port != 0
    except ValueError:
        return False


def require_worker_broker(environ=None) -> str:
    """Fail worker startup unless an explicit Redis endpoint is configured."""
    env = os.environ if environ is None else environ
    value = str(env.get("SCENTHUNTER_REDIS_URL", "")).strip()
    if not queue_is_configured(env):
        raise RuntimeError(
            "SCENTHUNTER_REDIS_URL must be an explicit redis:// or rediss:// URL "
            "with a hostname before the catalog worker can start"
        )
    return value


# Celery may otherwise apply its own localhost broker default. Guard the
# worker lifecycle rather than opening a Redis connection at module import.
from celery.signals import worker_init


@worker_init.connect
def _require_explicit_worker_broker(**_kwargs):
    require_worker_broker()
