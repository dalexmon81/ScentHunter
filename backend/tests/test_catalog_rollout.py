from app.services.catalog_rollout import (
    catalog_rollout_decision,
    compare_search_payloads,
)


def test_catalog_rollout_is_disabled_by_default():
    decision = catalog_rollout_decision("Sauvage", environ={})
    assert decision["enabled"] is False
    assert decision["traffic_percent"] == 0
    assert decision["use_catalog"] is False
    assert decision["run_shadow"] is False


def test_master_switch_alone_does_not_route_traffic():
    decision = catalog_rollout_decision(
        "Sauvage",
        "cohort-1",
        environ={"SCENTHUNTER_CATALOG_SEARCH_ENABLED": "1"},
    )
    assert decision["traffic_percent"] == 0
    assert decision["use_catalog"] is False


def test_explicit_full_percentage_is_required_for_full_catalog_routing():
    decision = catalog_rollout_decision(
        "Sauvage",
        "cohort-1",
        environ={
            "SCENTHUNTER_CATALOG_SEARCH_ENABLED": "1",
            "SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT": "100",
        },
    )
    assert decision["traffic_percent"] == 100
    assert decision["use_catalog"] is True
    assert decision["run_shadow"] is False


def test_canary_percentage_is_deterministic_for_a_stable_key():
    env = {
        "SCENTHUNTER_CATALOG_SEARCH_ENABLED": "1",
        "SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT": "25",
    }
    first = catalog_rollout_decision("Sauvage", "session-123", environ=env)
    second = catalog_rollout_decision("Sauvage", "session-123", environ=env)
    assert first == second
    assert 0 <= first["bucket"] < 100
    assert first["use_catalog"] is (first["bucket"] < 25)


def test_invalid_or_disabled_percentage_fails_closed():
    disabled = catalog_rollout_decision(
        "Sauvage",
        environ={
            "SCENTHUNTER_CATALOG_SEARCH_ENABLED": "0",
            "SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT": "100",
        },
    )
    invalid = catalog_rollout_decision(
        "Sauvage",
        environ={
            "SCENTHUNTER_CATALOG_SEARCH_ENABLED": "1",
            "SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT": "not-a-number",
        },
    )
    assert disabled["use_catalog"] is False
    assert invalid["traffic_percent"] == 0
    assert invalid["use_catalog"] is False


def test_shadow_mode_reads_catalog_without_selecting_catalog_response():
    decision = catalog_rollout_decision(
        "Sauvage",
        "session-123",
        environ={"SCENTHUNTER_CATALOG_SEARCH_SHADOW": "1"},
    )
    assert decision["run_shadow"] is True
    assert decision["use_catalog"] is False


def test_shadow_comparison_reports_product_and_offer_overlap():
    legacy = [
        {
            "brand": "Dior",
            "name": "Sauvage",
            "offers": [
                {"store": "notino", "url": "https://shop.invalid/a/", "currency": "EUR"},
                {"store": "deloox", "url": "https://shop.invalid/b", "currency": "EUR"},
            ],
        }
    ]
    catalog = {
        "results": [
            {
                "canonical_brand": "Dior",
                "canonical_name": "Sauvage",
                "offers": [
                    {"store": "notino", "url": "https://shop.invalid/a", "currency": "EUR"},
                    {"store": "sabina", "url": "https://shop.invalid/c", "currency": "EUR"},
                ],
            }
        ]
    }

    comparison = compare_search_payloads(legacy, catalog)
    assert comparison["status"] == "compared"
    assert comparison["shared_product_count"] == 1
    assert comparison["legacy_only_product_count"] == 0
    assert comparison["catalog_only_product_count"] == 0
    assert comparison["shared_offer_count"] == 1
    assert comparison["legacy_only_offer_count"] == 1
    assert comparison["catalog_only_offer_count"] == 1
    assert comparison["product_overlap_ratio"] == 1.0
    assert comparison["offer_overlap_ratio"] == 0.3333


def test_search_start_routes_full_canary_to_catalog_without_starting_legacy_job(monkeypatch):
    import main

    monkeypatch.setenv("SCENTHUNTER_CATALOG_SEARCH_ENABLED", "1")
    monkeypatch.setenv("SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT", "100")
    called = []
    monkeypatch.setattr(
        main,
        "phase7_search_catalog_for_frontend",
        lambda query: {"query": query, "results": [], "count": 0},
    )
    monkeypatch.setattr(main, "_new_job", lambda query: called.append(query))

    response = main.search_start("Sauvage", None)

    assert response["catalog_rollout"]["mode"] == "catalog"
    assert response["catalog_rollout"]["traffic_percent"] == 100
    assert called == []


def test_search_start_shadow_reads_catalog_but_serves_legacy_snapshot(monkeypatch):
    import main

    monkeypatch.setenv("SCENTHUNTER_CATALOG_SEARCH_ENABLED", "0")
    monkeypatch.setenv("SCENTHUNTER_CATALOG_SEARCH_SHADOW", "1")
    monkeypatch.setenv("SEARCH_START_WAIT_SECONDS", "0")
    monkeypatch.setattr(main, "_CATALOG_BOOTSTRAP_RUNNING", False)
    monkeypatch.setattr(main, "_CATALOG_BOOTSTRAP_DONE", True)
    monkeypatch.setattr(main, "_CATALOG_BOOTSTRAP_ERROR", None)
    monkeypatch.setattr(main, "_cancel_active_jobs", lambda **kwargs: True)
    called = []

    def fake_catalog_search(query):
        called.append(query)
        return {
            "query": query,
            "results": [{"brand": "Dior", "fragrance": "Sauvage", "offers": []}],
            "count": 1,
        }

    monkeypatch.setattr(main, "phase7_search_catalog_for_frontend", fake_catalog_search)

    threads = []

    class NoStartThread:
        def __init__(self, *args, **kwargs):
            self.target = kwargs.get("target") or (args[0] if args else None)
            self.args = kwargs.get("args", ())
            threads.append(self)

        def start(self):
            return None

    monkeypatch.setattr(main.threading, "Thread", NoStartThread)
    response = main.search_start("Sauvage", "stable-session-1")
    job_id = response["job_id"]
    try:
        assert response["catalog_rollout"]["mode"] == "shadow"
        # The catalog lookup must not run inline and delay the legacy response.
        assert called == []
        shadow_threads = [thread for thread in threads if thread.target == main._run_catalog_shadow]
        assert len(shadow_threads) == 1
        shadow_threads[0].target(*shadow_threads[0].args)
        assert main.JOBS[job_id]["catalog_shadow_result"]["count"] == 1
        assert response["results"] == []
    finally:
        with main.JOBS_LOCK:
            main.JOBS.pop(job_id, None)
