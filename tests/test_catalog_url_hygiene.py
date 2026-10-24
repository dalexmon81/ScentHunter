"""Tests for the opt-in Deloox catalog URL hygiene repair."""
from backend.scenthunter_next_engine.catalog_url_hygiene import classify_invalid_urls


def test_classifies_stale_search_and_homepage_rows_but_keeps_numeric_products():
    rows = [
        {"store": "deloox", "url": "https://www.deloox.nl/zoeken.html", "slug": "zoeken", "active": 1},
        {"store": "deloox", "url": "https://www.deloox.lu/chercher.html", "slug": "chercher", "active": 1},
        {"store": "deloox", "url": "https://www.deloox.com/", "slug": "", "active": 1},
        {
            "store": "deloox",
            "url": "https://www.deloox.com/product/1380881/chloe-le-parfum-150-ml.html",
            "slug": "chloe-le-parfum-150-ml",
            "active": 1,
        },
        {"store": "deloox", "url": "https://www.deloox.com/search.html", "slug": "search", "active": 0},
    ]

    invalid = classify_invalid_urls(rows)

    assert {row["url"] for row in invalid} == {
        "https://www.deloox.nl/zoeken.html",
        "https://www.deloox.lu/chercher.html",
        "https://www.deloox.com/",
    }
    assert all(row["reason"] == "rejected_by_current_product_url_admission" for row in invalid)
