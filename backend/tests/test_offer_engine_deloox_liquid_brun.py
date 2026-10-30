"""Real-catalog regression for the Deloox Liquid Brun size split."""
from decimal import Decimal
from pathlib import Path
import unittest

from backend.offer_engine.contracts import Availability, OfferObservation, RetailerListing, Verification
from backend.offer_engine.resolver import resolve_observation
from backend.offer_engine.policy import OfferPolicy
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


class DelooxLiquidBrunOfferEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
        cls.matcher = CanonicalMatcher(catalog)

    def _resolve(self, *, size, title, url, gtin, availability, price):
        listing = RetailerListing(
            retailer="deloox",
            external_id=url.split("/")[4],
            product_url=url,
            raw_title=title,
            raw_brand="French Avenue",
            raw_size_ml=size,
            raw_gtin=gtin,
            market="BE",
        )
        parsed_page = {
            "name": title,
            "brand": "French Avenue",
            "size_ml": size,
            "attributes": {"size_ml": {"value": size}},
            "identity": {"gtin": {"value": gtin}} if gtin else {},
            "raw_data": {"jsonld": {"gtin13": gtin}} if gtin else {},
        }
        observation = OfferObservation.now(
            listing_key=f"deloox:{listing.external_id}",
            price=price,
            currency="EUR",
            availability=availability,
            source="product_page",
            verification=Verification.UNVERIFIED,
            evidence_url=url,
            evidence_hash="sha256:fixture-evidence",
            raw_payload={"parsed_page": parsed_page},
        )
        return resolve_observation(listing, observation, self.matcher)

    def test_limited_edition_150ml_resolves_to_its_own_variant_and_stays_sold_out(self):
        result = self._resolve(
            size=150,
            title="French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml",
            url="https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html",
            gtin="6298042001831",
            availability=Availability.OUT_OF_STOCK,
            price=None,
        )
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.observation.product_id, "SH-0031")
        self.assertEqual(result.observation.variant_id, "VAR-f5aff76b4bb5de8a")
        self.assertEqual(result.observation.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(result.observation.price)
        self.assertFalse(OfferPolicy().evaluate(result.observation).publish)

    def test_standard_100ml_never_maps_to_limited_edition_150ml(self):
        result = self._resolve(
            size=100,
            title="French Avenue Liquid Brun Eau de Parfum 100 ml",
            url="https://www.deloox.be/produit/1355229/french-avenue-liquid-brun-eau-de-parfum-100-ml.html",
            gtin=None,
            availability=Availability.IN_STOCK,
            price=Decimal("49.95"),
        )
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.observation.product_id, "SH-0030")
        self.assertEqual(result.observation.variant_id, "VAR-f87146c82d167f4c")
        self.assertNotEqual(result.observation.variant_id, "VAR-f5aff76b4bb5de8a")


if __name__ == "__main__":
    unittest.main()
