from backend.scrapers.bplatz import scraper


def test_bplatz_keeps_search_hit_when_shopify_handle_omits_brand_and_size():
    candidates = []
    seen = set()

    scraper.add_candidate(
        "/products/liquid-brun-extrait",
        "French Avenue Liquid Brun Extrait 100 ml",
        candidates,
        seen,
        evidence="French Avenue Liquid Brun Extrait de Parfum 100 ml",
    )

    assert candidates == ["https://en.bplatz.de/products/liquid-brun-extrait"]


def test_bplatz_still_rejects_candidate_without_matching_title_or_handle():
    candidates = []
    seen = set()

    scraper.add_candidate(
        "/products/another-fragrance",
        "French Avenue Liquid Brun Extrait 100 ml",
        candidates,
        seen,
        evidence="Another fragrance by another brand 50 ml",
    )

    assert candidates == []
