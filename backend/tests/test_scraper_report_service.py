from app.services.scraper_report import normalize_scraper_report


def test_dict_report_preserves_explicit_status_and_verification():
    row = {"name": "Sauvage"}
    report = normalize_scraper_report({
        "status": "partial",
        "verified": False,
        "results": [row, "not-a-row"],
        "details": {"source": "fixture"},
    })

    assert report == {
        "status": "partial",
        "verified": False,
        "results": [row],
        "error": None,
        "details": {"source": "fixture"},
    }


def test_dict_report_accepts_legacy_products_key_and_details_override():
    row = {"name": "Sauvage"}
    report = normalize_scraper_report({
        "products": [row],
        "details": {"verified": False},
    })

    assert report["status"] == "success"
    assert report["verified"] is False
    assert report["results"] == [row]


def test_empty_legacy_list_is_unverified_not_not_found():
    report = normalize_scraper_report([])

    assert report["status"] == "unavailable"
    assert report["verified"] is False
    assert report["results"] == []
    assert report["error"] == "legacy_scraper_returned_unverified_empty_list"


def test_none_is_a_contract_error():
    report = normalize_scraper_report(None)

    assert report["status"] == "error"
    assert report["verified"] is False
    assert report["error"] == "scraper_returned_none"


def test_tuple_and_generator_legacy_results_are_supported():
    first = {"name": "Sauvage"}
    second = {"name": "Eros"}

    assert normalize_scraper_report((first, second))["results"] == [first, second]
    assert normalize_scraper_report(row for row in (first, second))["results"] == [
        first, second
    ]


def test_unknown_dict_status_keeps_legacy_success_default():
    report = normalize_scraper_report({"status": "unexpected", "results": []})

    assert report["status"] == "success"
    assert report["verified"] is True
    assert report["results"] == []
