"""End-to-end Deloox connector contract tests against the reviewed catalog."""
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.offer_engine.connectors.deloox import DelooxConnector
from backend.offer_engine.contracts import Availability
from backend.offer_engine.policy import OfferPolicy
from backend.offer_engine.resolver import resolve_observation
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


URL_100 = "https://www.deloox.be/produit/1355229/french-avenue-liquid-brun-eau-de-parfum-100-ml.html"
URL_150 = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"


def page(url, title, size, availability, price, gtin=None):
    return {
        "url": url,
        "name": title,
        "brand": "French Avenue",
        "sku": url.split("/")[4],
        "gtin": gtin,
        "identity": {
            "sku": {"value": url.split("/")[4], "source": "jsonld"},
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
        },
        "attributes": {
            "size_ml": {"value": size, "source": "product_name_or_url"},
            "concentration": {"value": "Extrait de Parfum" if size == 150 else "Eau de Parfum"},
        },
        "offer": {"price": price, "currency": "EUR", "availability": availability},
        "raw_data": {"jsonld": {"gtin13": gtin} if gtin else {}},
    }


class DelooxConnectorPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
        cls.matcher = CanonicalMatcher(catalog)

    def _run(self, url, title, size, availability, price, gtin=None):
        parsed = page(url, title, size, availability, price, gtin)
        with patch("backend.offer_engine.connectors.deloox.scraper.search", return_value=[parsed]), \
             patch("backend.offer_engine.connectors.deloox.scraper.extract_product_page", return_value=parsed):
            connector = DelooxConnector(session=object())
            listing = next(iter(connector.discover("Liquid Brun")))
            observation = connector.observe(listing)

        resolved = resolve_observation(listing, observation, self.matcher)
        return listing, observation, resolved

    def test_150ml_limited_edition_keeps_out_of_stock_and_no_price(self):
        listing, raw, resolved = self._run(
            URL_150,
            "French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml",
            150, "out_of_stock", None, "6298042001831",
        )
        self.assertEqual(listing.raw_size_ml, 150)
        self.assertEqual(raw.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(raw.price)
        self.assertEqual(raw.verification.value, "unverified")
        self.assertEqual(raw.listing_key, "deloox:1385920")
        self.assertEqual(resolved.status, "matched")
        self.assertEqual(resolved.observation.product_id, "SH-0031")
        self.assertEqual(resolved.observation.variant_id, "VAR-f5aff76b4bb5de8a")
        self.assertFalse(OfferPolicy().evaluate(resolved.observation).publish)

    def test_100ml_standard_is_not_collapsed_into_150ml_limited_edition(self):
        listing, raw, resolved = self._run(
            URL_100,
            "French Avenue Liquid Brun Eau de Parfum 100 ml",
            100, "in_stock", 49.95,
        )
        self.assertEqual(listing.raw_size_ml, 100)
        self.assertEqual(raw.price, Decimal("49.95"))
        self.assertEqual(resolved.status, "matched")
        self.assertEqual(resolved.observation.product_id, "SH-0030")
        self.assertEqual(resolved.observation.variant_id, "VAR-f87146c82d167f4c")
        self.assertNotEqual(resolved.observation.variant_id, "VAR-f5aff76b4bb5de8a")


if __name__ == "__main__":
    unittest.main()
