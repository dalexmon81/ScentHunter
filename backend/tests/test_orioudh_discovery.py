import unittest
from unittest.mock import patch

from backend.scrapers.orioudh import scraper


class FakeResponse:
    status_code = 200
    ok = True
    text = ""

    def __init__(self, payload=None):
        self.payload = payload or {}

    def json(self):
        return self.payload

    def close(self):
        pass


class FakeSession:
    def __init__(self):
        self.suggest_queries = []

    def get(self, url, params=None, **kwargs):
        if url.endswith("/search/suggest.json"):
            query = params.get("q", "")
            self.suggest_queries.append(query)
            products = []
            if query == "Liquid Brun":
                products = [{
                    "title": "Liquid Brun Eau de Parfum 100 ml",
                    "vendor": "French Avenue",
                    "url": "/products/liquid-brun",
                }]
            return FakeResponse({
                "resources": {"results": {"products": products}}
            })
        if url.endswith("/search.json"):
            return FakeResponse({"products": []})
        return FakeResponse()


class OrioudhDiscoveryTests(unittest.TestCase):
    def test_search_probes_trailing_product_name_pair_after_brand_pair(self):
        session = FakeSession()
        urls, errors, verified = scraper._discovery(
            session, "French Avenue Liquid Brun"
        )
        self.assertTrue(verified)
        self.assertEqual(errors, [])
        self.assertIn("french avenue", session.suggest_queries)
        self.assertIn("liquid brun", session.suggest_queries)
        self.assertEqual(urls, ["https://orioudh.com/products/liquid-brun"])

    def test_trailing_pair_does_not_weaken_full_query_admission(self):
        session = FakeSession()
        original = scraper._matches
        with patch.object(scraper, "_matches", side_effect=lambda text, query: original(text, query)):
            urls, _, _ = scraper._discovery(session, "French Avenue Liquid Brun")
        self.assertEqual(urls, ["https://orioudh.com/products/liquid-brun"])


if __name__ == "__main__":
    unittest.main()
