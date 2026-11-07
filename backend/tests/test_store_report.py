from app.services.store_report import empty_store_report


def test_empty_store_report_preserves_standard_unverified_shape():
    assert empty_store_report("sabina") == {
        "store": "sabina",
        "status": "error",
        "elapsed": 0.0,
        "count": 0,
        "results": [],
        "error": None,
        "verified": False,
    }


def test_empty_store_report_rounds_elapsed_and_preserves_error_status():
    report = empty_store_report(
        "deloox",
        status="timeout",
        elapsed=1.23456,
        error="store_timeout_1s",
    )

    assert report == {
        "store": "deloox",
        "status": "timeout",
        "elapsed": 1.235,
        "count": 0,
        "results": [],
        "error": "store_timeout_1s",
        "verified": False,
    }


def test_empty_store_report_returns_independent_results_lists():
    first = empty_store_report("sabina")
    second = empty_store_report("deloox")

    first["results"].append({"name": "test"})

    assert second["results"] == []
