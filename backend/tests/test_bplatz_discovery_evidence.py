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


def test_bplatz_discovers_limited_edition_when_shopify_handle_omits_brand():
    candidates = []
    seen = set()

    scraper.add_candidate(
        "/products/liquid-brun-limited-edition-eau-de-parfum-150-ml",
        "French Avenue Liquid Brun Limited Edition 150 ml",
        candidates,
        seen,
    )

    assert candidates == [
        "https://en.bplatz.de/products/liquid-brun-limited-edition-eau-de-parfum-150-ml"
    ]


def test_bplatz_search_normalization_matches_accented_query_terms():
    assert scraper.tokens("Rayhaan élixir") == ["rayhaan", "elixir"]
    assert scraper.matches("Rayhaan Elixir Eau de Parfum 100 ml", "Rayhaan élixir")
    assert scraper.matches("Rayhaan Élixir Eau de Parfum 100 ml", "Rayhaan Elixir")


def test_bplatz_reports_candidate_rejected_by_product_page(monkeypatch):
    class Response:
        status_code = 200
        url = "https://en.bplatz.de/products/not-liquid-brun"
        text = "<html><body><h1>Another fragrance 100 ml</h1></body></html>"

        def close(self):
            pass

    class Session:
        def get(self, *args, **kwargs):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(scraper.requests, "Session", Session)
    monkeypatch.setattr(
        scraper,
        "discover",
        lambda session, query: (
            ["https://en.bplatz.de/products/not-liquid-brun"], [], True
        ),
    )

    report = scraper._search_report("French Avenue Liquid Brun 100 ml")

    assert report["verified"] is True
    assert report["results"] == []
    assert report["details"]["candidate_count"] == 1
    assert report["details"]["verified_empty"] is False
    assert report["details"]["product_page_rejection_count"] == 1
    assert report["details"]["product_page_rejections"][0]["reason"] == "product_page_title_mismatch"
