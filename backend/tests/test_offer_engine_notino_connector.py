import unittest
from pathlib import Path

from backend.offer_engine.resolver import resolve_observation
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
from backend.offer_engine.connectors.notino import NotinoFeedConnector
from backend.offer_engine.contracts import Availability, Verification


FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>
  <item>
    <g:id>LB100</g:id><g:title>French Avenue Liquid Brun Eau de Parfum 100 ml</g:title>
    <g:brand>French Avenue</g:brand><g:gtin>6298042001008</g:gtin>
    <g:price>49.95 EUR</g:price><g:availability>in stock</g:availability>
    <g:link>https://www.notino.fr/french-avenue/liquid-brun/</g:link>
    <g:size>100 ml</g:size>
  </item>
  <item>
    <g:id>LB150</g:id><g:title>French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml</g:title>
    <g:brand>French Avenue</g:brand><g:gtin>6298042001831</g:gtin>
    <g:currency>EUR</g:currency><g:availability>out of stock</g:availability>
    <g:link>https://www.notino.fr/french-avenue/liquid-brun-limited/</g:link>
    <g:size>150 ml</g:size>
  </item>
</channel></rss>"""


class NotinoFeedConnectorTests(unittest.TestCase):
    def setUp(self):
        self.connector = NotinoFeedConnector(fetch_feed=lambda: FEED)

    def test_discovery_keeps_size_variants_separate(self):
        rows = list(self.connector.discover("Liquid Brun"))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.raw_size_ml for row in rows}, {100, 150})
        self.assertEqual({row.market for row in rows}, {"FR"})
        self.assertEqual(len({row.external_id for row in rows}), 2)

    def test_size_query_selects_only_exact_feed_variant(self):
        rows = list(self.connector.discover("Liquid Brun 150 ml"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].raw_size_ml, 150)
        self.assertEqual(rows[0].raw_gtin, "6298042001831")

    def test_in_stock_feed_observation_is_unverified_until_canonical_resolution(self):
        listing = next(iter(self.connector.discover("Liquid Brun 100 ml")))
        observation = self.connector.observe(listing)
        self.assertEqual(observation.availability, Availability.IN_STOCK)
        self.assertEqual(str(observation.price), "49.95")
        self.assertEqual(observation.source, "feed")
        self.assertEqual(observation.verification, Verification.UNVERIFIED)
        self.assertEqual(observation.evidence_url, listing.product_url)
        self.assertTrue(observation.evidence_hash.startswith("sha256:"))

    def test_out_of_stock_feed_observation_never_carries_a_price(self):
        listing = next(iter(self.connector.discover("Liquid Brun 150 ml")))
        observation = self.connector.observe(listing)
        self.assertEqual(observation.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(observation.price)
        self.assertEqual(observation.verification, Verification.UNVERIFIED)

    def test_feed_variants_resolve_against_real_canonical_catalog(self):
        root = Path(__file__).resolve().parents[2]
        catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
        matcher = CanonicalMatcher(catalog)
        rows = list(self.connector.discover("Liquid Brun"))
        resolved = {
            row.raw_size_ml: resolve_observation(row, self.connector.observe(row), matcher)
            for row in rows
        }
        self.assertEqual(resolved[100].status, "matched")
        self.assertEqual(resolved[100].observation.product_id, "SH-0030")
        self.assertEqual(resolved[100].observation.variant_id, "VAR-f87146c82d167f4c")
        self.assertEqual(resolved[150].status, "matched")
        self.assertEqual(resolved[150].observation.product_id, "SH-0031")
        self.assertEqual(resolved[150].observation.variant_id, "VAR-f5aff76b4bb5de8a")
        self.assertEqual(resolved[150].observation.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(resolved[150].observation.price)

    def test_observation_rejects_listing_not_in_current_discovery(self):
        listing = next(iter(self.connector.discover("Liquid Brun 100 ml")))
        self.connector.discover("different product")
        with self.assertRaisesRegex(RuntimeError, "not_in_current_discovery"):
            self.connector.observe(listing)


if __name__ == "__main__":
    unittest.main()
