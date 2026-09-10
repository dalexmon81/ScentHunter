import unittest
from unittest.mock import patch

from scrapers.bplatz import scraper as bplatz
from scrapers.common.discovery import (
    discover_shopify_product_urls,
    extract_json_ld_products,
)


class _Response:
    def __init__(self, *, ok=True, data=None, text=""):
        self.ok = ok
        self._data = data
        self.text = text
        self.closed = False

    def json(self):
        if self._data is None:
            raise ValueError("no json payload")
        return self._data

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, params=None, headers=None, timeout=None):
        key = (url, tuple(sorted((params or {}).items())))
        return self.responses[key]


class ScraperDiscoveryTests(unittest.TestCase):
    def test_extract_json_ld_products_only_returns_product_nodes(self):
        html = """
        <script type="application/ld+json">
        {"offers":{"price":"9.99"},"brand":"wrapper"}
        </script>
        <script type="application/ld+json">
        {"@graph":[
          {"@type":"BreadcrumbList","name":"crumbs"},
          {"@type":"Product","name":"Real Perfume","offers":{"price":"19.99"}}
        ]}
        </script>
        """

        records = extract_json_ld_products(html)

        self.assertEqual([record.get("name") for record in records], ["Real Perfume"])

    def test_discover_shopify_product_urls_reads_only_known_product_arrays(self):
        session = _Session({
            (
                "https://example.com/search/suggest.json",
                (
                    ("q", "Real Perfume"),
                    ("resources[limit]", 12),
                    ("resources[options][unavailable_products]", "show"),
                    ("resources[type]", "product"),
                ),
            ): _Response(data={
                "resources": {
                    "results": {
                        "products": [
                            {"title": "Real Perfume", "vendor": "Brand", "url": "/products/real-perfume"},
                        ],
                        "collections": [
                            {"title": "Noise", "url": "/products/should-not-pass"},
                        ],
                    }
                },
                "brand": {"url": "/products/wrong-wrapper"},
            }),
            (
                "https://example.com/search.json",
                (
                    ("limit", 12),
                    ("q", "Real Perfume"),
                    ("type", "product"),
                ),
            ): _Response(data={"products": []}),
            (
                "https://example.com/search",
                (
                    ("q", "Real Perfume"),
                    ("type", "product"),
                ),
            ): _Response(text=""),
        })

        urls = discover_shopify_product_urls(
            session,
            base_url="https://example.com",
            request_query="Real Perfume",
            match_query="Real Perfume",
            query_matcher=lambda text, query: query.lower() in text.lower(),
            headers={},
            timeout=1,
            limit=8,
        )

        self.assertEqual(urls, ["https://example.com/products/real-perfume"])

    def test_bplatz_candidate_urls_preserves_predictive_order(self):
        calls = []

        def fake_discovery(session, **kwargs):
            calls.append((kwargs["request_query"], kwargs["allow_search_json"]))
            if kwargs["allow_search_json"]:
                self.fail("fallback discovery should not run when predictive URLs exist")
            mapping = {
                "Liquid Brun": [
                    "https://bplatz.de/products/liquid-brun",
                    "https://bplatz.de/products/liquid-brun-intense",
                ],
                "liquid": [
                    "https://bplatz.de/products/liquid-brun-intense",
                    "https://bplatz.de/products/liquid-gold",
                ],
                "brun": [
                    "https://bplatz.de/products/brun-reserve",
                ],
            }
            return mapping.get(kwargs["request_query"], [])

        with patch.object(bplatz, "discover_shopify_product_urls", side_effect=fake_discovery):
            urls = bplatz.candidate_urls(object(), "Liquid Brun")

        self.assertEqual(
            urls,
            [
                "https://bplatz.de/products/liquid-brun",
                "https://bplatz.de/products/liquid-brun-intense",
                "https://bplatz.de/products/liquid-gold",
                "https://bplatz.de/products/brun-reserve",
            ],
        )
        self.assertEqual(len(calls), 3)

    def test_bplatz_candidate_urls_runs_full_fallback_once(self):
        calls = []

        def fake_discovery(session, **kwargs):
            full_discovery = kwargs.get("allow_search_json", True)
            calls.append((kwargs["request_query"], full_discovery))
            if full_discovery:
                return [
                    "https://bplatz.de/products/fallback-one",
                    "https://bplatz.de/products/fallback-two",
                ]
            return []

        with patch.object(bplatz, "discover_shopify_product_urls", side_effect=fake_discovery):
            urls = bplatz.candidate_urls(object(), "Liquid Brun")

        self.assertEqual(
            urls,
            [
                "https://bplatz.de/products/fallback-one",
                "https://bplatz.de/products/fallback-two",
            ],
        )
        self.assertEqual(sum(1 for _, full in calls if full), 1)


if __name__ == "__main__":
    unittest.main()
