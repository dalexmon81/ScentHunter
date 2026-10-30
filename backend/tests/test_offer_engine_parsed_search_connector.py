import unittest

from backend.offer_engine.connectors.parsed_search import ParsedSearchConnector
from backend.offer_engine.contracts import Availability, Verification


class FakeScraper:
    BASE_URL = "https://www.parfum-zentrum.de"

    def __init__(self, result):
        self.result = result

    def search_stream(self, query):
        return self.result


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
        self.assertEqual(observation.price, 49.95)
        self.assertEqual(observation.availability, Availability.IN_STOCK)
        self.assertEqual(observation.verification, Verification.UNVERIFIED)
        self.assertEqual(observation.raw_payload["parsed_page"]["attributes"]["size_ml"]["value"], 100)
        self.assertEqual(observation.raw_payload["parsed_page"]["identity"]["gtin"]["value"], "6298042001008")

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
