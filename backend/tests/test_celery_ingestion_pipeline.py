from app.workers.celery_app import celery_app

def test_pipeline_declares_all_required_queues():
    names = {queue.name for queue in celery_app.conf.task_queues}
    assert {"discovery", "offers", "validation", "matching", "refresh", "dead_letter"} <= names

def test_pipeline_routes_jobs_to_separate_queues():
    routes = celery_app.conf.task_routes
    assert routes["app.workers.ingestion_tasks.discover_store_products"]["queue"] == "discovery"
    assert routes["app.workers.ingestion_tasks.fetch_store_offers"]["queue"] == "offers"
    assert routes["app.workers.ingestion_tasks.normalize_offer"]["queue"] == "validation"
    assert routes["app.workers.ingestion_tasks.validate_offer"]["queue"] == "validation"
    assert routes["app.workers.ingestion_tasks.match_offer_to_variant"]["queue"] == "matching"
    assert routes["app.workers.ingestion_tasks.refresh_price_and_stock"]["queue"] == "refresh"
    assert routes["app.workers.ingestion_tasks.record_dead_letter"]["queue"] == "dead_letter"

def test_pipeline_beat_cadence_is_catalog_first():
    schedule = celery_app.conf.beat_schedule
    assert schedule["discover-store-products-daily"]["schedule"] == 86400.0
    assert schedule["fetch-store-offers-every-eight-hours"]["schedule"] == 28800.0
    assert schedule["refresh-main-store-prices-every-thirty-minutes"]["schedule"] == 1800.0
