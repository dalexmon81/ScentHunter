"""Celery application and queue topology for catalog-first ingestion."""
from __future__ import annotations

import os
from celery import Celery
from kombu import Queue

BROKER_URL = os.environ.get("SCENTHUNTER_REDIS_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.environ.get("SCENTHUNTER_CELERY_RESULT_BACKEND", BROKER_URL)

QUEUES = (
    Queue("discovery"),
    Queue("offers"),
    Queue("validation"),
    Queue("matching"),
    Queue("refresh"),
    Queue("dead_letter"),
)

celery_app = Celery(
    "scenthunter_ingestion",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["app.workers.ingestion_tasks"],
)
celery_app.conf.update(
    task_default_queue="offers",
    task_queues=QUEUES,
    task_routes={
        "app.workers.ingestion_tasks.discover_store_products": {"queue": "discovery"},
        "app.workers.ingestion_tasks.fetch_store_offers": {"queue": "offers"},
        "app.workers.ingestion_tasks.normalize_offer": {"queue": "validation"},
        "app.workers.ingestion_tasks.validate_offer": {"queue": "validation"},
        "app.workers.ingestion_tasks.match_offer_to_variant": {"queue": "matching"},
        "app.workers.ingestion_tasks.promote_matched_offers_task": {"queue": "offers"},
        "app.workers.ingestion_tasks.refresh_price_and_stock": {"queue": "refresh"},
        "app.workers.ingestion_tasks.quarantine_failed_connector": {"queue": "dead_letter"},
        "app.workers.ingestion_tasks.reprocess_failed_offers": {"queue": "offers"},
        "app.workers.ingestion_tasks.record_dead_letter": {"queue": "dead_letter"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=os.environ.get("SCENTHUNTER_TIMEZONE", "Europe/Luxembourg"),
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_send_sent_event=True,
    broker_transport_options={"visibility_timeout": 3600},
    result_expires=86400,
    beat_schedule={
        "discover-store-products-daily": {
            "task": "app.workers.ingestion_tasks.enqueue_discovery_for_configured_stores",
            "schedule": 86400.0,
            "options": {"queue": "discovery"},
        },
        "fetch-store-offers-every-eight-hours": {
            "task": "app.workers.ingestion_tasks.enqueue_offer_collection_for_configured_stores",
            "schedule": 28800.0,
            "options": {"queue": "offers"},
        },
        "refresh-main-store-prices-every-thirty-minutes": {
            "task": "app.workers.ingestion_tasks.enqueue_refresh_for_active_stores",
            "schedule": 1800.0,
            "options": {"queue": "refresh"},
        },
    },
)

app = celery_app
