import unittest
from scenthunter_next_engine.adapter import OfferPipeline
from scenthunter_next_engine.models import RetailerOfferRecord


class FixtureAdapter:
    store_key = "shop_a"
    parser_version = "fixture-v1"

    def discover(self, *, limit):
        return ["https://shop.example/a", "https://shop.example/a", "https://shop.example/b"][:limit]

    def fetch(self, url):
        return b"fixture"

    def parse(self, url, body):
        return RetailerOfferRecord(
            store="shop_a", source_url=url, product_url=url,
            title="Brand Fragrance 100 ml Eau de Parfum", brand="Brand",
            price_minor=12000, currency="EUR",
            observed_at="2026-01-01T00:00:00+00:00",
            parser_version="fixture-v1", trace_id="trace", raw_price="120.00",
            availability="in_stock", size_ml=100, concentration="Eau de Parfum",
        )


class PipelineTests(unittest.TestCase):
    def test_discovery_deduplicates(self):
        self.assertEqual(OfferPipeline(FixtureAdapter()).discover(),
                         ["https://shop.example/a", "https://shop.example/b"])

    def test_observe(self):
        self.assertEqual(OfferPipeline(FixtureAdapter()).observe("https://shop.example/a").store, "shop_a")


if __name__ == "__main__":
    unittest.main()
