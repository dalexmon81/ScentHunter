"""Celery task contracts; fail closed until runtime handlers are wired."""
from __future__ import annotations
from celery import Task
from app.workers.celery_app import celery_app

class HandlerNotConfigured(RuntimeError):
    pass

def _execute(stage: str, payload: dict):
    if not isinstance(payload, dict):
        raise TypeError("task payload must be a JSON object")
    from app.workers.runtime import get_handler
    handler = get_handler(stage)
    if handler is None:
        raise HandlerNotConfigured(f"worker handler is not configured: {stage}")
    return handler(payload)

class RetryableCatalogTask(Task):
    autoretry_for = (TimeoutError, ConnectionError)
    retry_backoff = True
    retry_backoff_max = 900
    retry_jitter = True
    max_retries = 5
    acks_late = True
    reject_on_worker_lost = True

@celery_app.task(bind=True, base=RetryableCatalogTask, name="app.workers.tasks.discover_store_products")
def discover_store_products(self, payload: dict):
    return _execute("discover", payload)
@celery_app.task(bind=True, base=RetryableCatalogTask, name="app.workers.tasks.fetch_store_offers")
def fetch_store_offers(self, payload: dict):
    return _execute("fetch", payload)
@celery_app.task(bind=True, base=RetryableCatalogTask, name="app.workers.tasks.normalize_offer")
def normalize_offer(self, payload: dict):
    return _execute("normalize", payload)
@celery_app.task(bind=True, base=RetryableCatalogTask, name="app.workers.tasks.match_offer_to_variant")
def match_offer_to_variant(self, payload: dict):
    return _execute("match", payload)
@celery_app.task(bind=True, base=RetryableCatalogTask, name="app.workers.tasks.validate_offer")
def validate_offer(self, payload: dict):
    return _execute("validate", payload)
@celery_app.task(bind=True, base=RetryableCatalogTask, name="app.workers.tasks.refresh_price_and_stock")
def refresh_price_and_stock(self, payload: dict):
    return _execute("refresh", payload)
@celery_app.task(bind=True, base=RetryableCatalogTask, name="app.workers.tasks.quarantine_failed_connector")
def quarantine_failed_connector(self, payload: dict):
    return _execute("quarantine", payload)
@celery_app.task(bind=True, base=RetryableCatalogTask, name="app.workers.tasks.reprocess_failed_offers")
def reprocess_failed_offers(self, payload: dict):
    return _execute("reprocess", payload)
