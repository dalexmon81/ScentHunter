import unittest

from backend.offer_engine.connectors.parsed_search import ParsedSearchConnector
from backend.offer_engine.contracts import Availability, Verification


class FakeScraper:
    BASE_URL = "https://www.parfum-zentrum.de"

    def __init__(self, result, page_overrides=None):
        self.result = result
        self.page_overrides = page_overrides or {}
        self.page_fetches = []

    def search_stream(self, query):
        return self.result

    def extract_product_page(self, session, url, query=""):
        self.page_fetches.append(url)
        row = next(
            item for item in self.result.get("results", [])
            if item.get("url") == url
        )
        page = dict(row)
        page.update(self.page_overrides)
        page["attributes"] = {
            "size_ml": {"value": page.get("size_ml")},
            "concentration": {"value": page.get("concentration")},
        }
        page["identity"] = {
            "gtin": {"value": page.get("gtin")},
            "sku": {"value": page.get("sku")},
        }
        page["offer"] = {
            "price": page.get("price_num"),
            "currency": page.get("currency", "EUR"),
            "availability": page.get("availability"),
        }
        page["url"] = self.page_overrides.get("url", url)
        return page


class ParsedSearchConnectorTests(unittest.TestCase):
    def _row(self, **updates):
        row = {
            "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
            "brand": "French Avenue",
            "url": "https://www.parfum-zentrum.de/liquid-brun-100.html",
            "sku": "LB100",
            "gtin": "6298042001008",
            "size_ml": 100,
            "concentration": "Eau de Parfum",
            "price_num": 49.95,
            "currency": "EUR",
            "availability": "in_stock",
        }
        row.update(updates)
        return row

    def test_discovery_and_observation_preserve_variant_and_gtin(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success",
                "verified": True,
                "results": [self._row()],
                "details": {},
            }),
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        observation = connector.observe(listing)
        self.assertEqual(listing.external_id, "LB100")
        self.assertEqual(listing.raw_size_ml, 100)
        self.assertEqual(listing.raw_gtin, "6298042001008")
        self.assertEqual(listing.market, "DE")
        self.assertEqual(str(observation.price), "49.95")
        self.assertEqual(observation.availability, Availability.IN_STOCK)
        self.assertEqual(connector._scraper.page_fetches, [listing.product_url])
        self.assertEqual(observation.raw_payload["evidence_source"], "fetched_product_detail")
        self.assertEqual(observation.verification, Verification.UNVERIFIED)
        self.assertEqual(observation.raw_payload["parsed_page"]["attributes"]["size_ml"]["value"], 100)
        self.assertEqual(observation.raw_payload["parsed_page"]["identity"]["gtin"]["value"], "6298042001008")

    def test_search_snippet_price_is_ignored_in_favor_of_product_page_price(self):
        scraper = FakeScraper(
            {
                "status": "success", "verified": True,
                "results": [self._row(price_num=49.95)],
            },
            page_overrides={"price_num": 37.40},
        )
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=scraper,
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        observation = connector.observe(listing)
        self.assertEqual(str(observation.price), "37.4")
        self.assertEqual(scraper.page_fetches, [listing.product_url])

    def test_reused_product_sku_does_not_collapse_different_sizes(self):
        rows = [
            self._row(url="https://www.parfum-zentrum.de/liquid-brun-100.html", size_ml=100),
            self._row(url="https://www.parfum-zentrum.de/liquid-brun-150.html", size_ml=150),
        ]
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True, "results": rows,
            }),
        )
        listings = list(connector.discover("Liquid Brun"))
        self.assertEqual(len(listings), 2)
        self.assertEqual({item.raw_size_ml for item in listings}, {100, 150})
        self.assertEqual(len({item.external_id for item in listings}), 2)

    def test_product_page_redirect_to_another_path_is_rejected(self):
        scraper = FakeScraper(
            {
                "status": "success", "verified": True,
                "results": [self._row()],
            },
            page_overrides={"url": "https://www.parfum-zentrum.de/another-product.html"},
        )
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=scraper,
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        with self.assertRaisesRegex(RuntimeError, "redirected_to_different_product"):
            connector.observe(listing)

    def test_verified_partial_discovery_keeps_page_verified_candidates(self):
        connector = ParsedSearchConnector(
            "bplatz",
            "scrapers.bplatz.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "partial",
                "verified": True,
                "results": [self._row()],
                "details": {"discovery_errors": [{"source": "search_json", "status": "error"}]},
            }),
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        observation = connector.observe(listing)
        self.assertEqual(listing.external_id, "LB100")
        self.assertEqual(observation.availability, Availability.IN_STOCK)

    def test_sold_out_result_never_keeps_a_stale_price(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [self._row(availability="out_of_stock")],
            }),
        )
        listing = next(iter(connector.discover("Liquid Brun")))
        observation = connector.observe(listing)
        self.assertEqual(observation.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(observation.price)

    def test_unknown_stock_is_not_guessed_from_available_boolean(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [self._row(availability=None, available=True)],
            }),
        )
        listing = next(iter(connector.discover("Liquid Brun")))
        observation = connector.observe(listing)
        self.assertEqual(observation.availability, Availability.UNKNOWN)

    def test_discovery_challenge_fails_closed(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "unavailable", "verified": False, "results": [],
                "details": {"client_challenge": True},
            }),
        )
        with self.assertRaisesRegex(RuntimeError, "parfumzentrum_discovery_unavailable"):
            list(connector.discover("Liquid Brun"))

    def test_foreign_host_result_is_rejected(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [self._row(url="https://www.sabina.com/wrong-store.html")],
            }),
        )
        self.assertEqual(list(connector.discover("Liquid Brun")), [])


if __name__ == "__main__":
    unittest.main()
