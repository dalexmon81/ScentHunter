import json
import tempfile
import unittest
from pathlib import Path

from backend.scripts.build_notino_catalog_expansion_review import build_expansion_proposals


class NotinoCatalogExpansionReviewTests(unittest.TestCase):
    def test_only_missing_brands_are_proposed_and_gtin_holds_are_explicit(self):
        xml = """<?xml version="1.0"?>
        <feed>
          <entry><id>KNOWN</id><brand>Dior</brand><title>Dior Sauvage Eau de Parfum 100 ml</title><gtin>8011003809202</gtin><product_type>Parfémy &gt; Parfémované vody</product_type><google_product_category>479</google_product_category><price>100 EUR</price><availability>in stock</availability><link>https://shop.example/known</link><last_updated>2026-11-10T10:00:00+01:00</last_updated></entry>
          <entry><id>NEW-A</id><brand>Al Haramain</brand><title>Al Haramain Amber Oud Eau de Parfum 100 ml</title><gtin>8011003809202</gtin><product_type>Parfémy &gt; Parfémované vody</product_type><google_product_category>479</google_product_category><price>80 EUR</price><availability>in stock</availability><link>https://shop.example/a</link><last_updated>2026-11-10T10:00:00+01:00</last_updated></entry>
          <entry><id>NEW-B</id><brand>Al Haramain</brand><title>Al Haramain Amber Oud Eau de Parfum 100 ml</title><gtin>8011003809202</gtin><product_type>Parfémy &gt; Parfémované vody</product_type><google_product_category>479</google_product_category><price>80 EUR</price><availability>in stock</availability><link>https://shop.example/b</link><last_updated>2026-11-10T10:00:00+01:00</last_updated></entry>
          <entry><id>NEW-INVALID</id><brand>Nishane</brand><title>Nishane Hacivat Eau de Parfum 100 ml</title><gtin>1234567890123</gtin><product_type>Parfémy &gt; Parfémované vody</product_type><google_product_category>479</google_product_category><price>150 EUR</price><availability>in stock</availability><link>https://shop.example/c</link><last_updated>2026-11-10T10:00:00+01:00</last_updated></entry>
          <entry><id>GIFT</id><brand>Al Haramain</brand><title>Gift Set</title><gtin>8011003809202</gtin><product_type>Parfémy &gt; Dárkové sady</product_type><google_product_category>479</google_product_category></entry>
        </feed>"""
        catalog = {"products": [{"product_id": "P1", "brand_name": "Dior"}], "variants": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feed = root / "feed.xml"
            catalog_path = root / "catalog.json"
            feed.write_text(xml, encoding="utf-8")
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            rows, summary = build_expansion_proposals(feed, catalog_path)

        by_id = {row["feed_external_id"]: row for row in rows}
        self.assertEqual(set(by_id), {"NEW-A", "NEW-B", "NEW-INVALID"})
        self.assertEqual(by_id["NEW-A"]["review_status"], "hold_duplicate_gtin")
        self.assertEqual(by_id["NEW-B"]["review_status"], "hold_duplicate_gtin")
        self.assertEqual(by_id["NEW-INVALID"]["review_status"], "hold_invalid_gtin")
        self.assertTrue(all(row["catalog_write_allowed"] is False for row in rows))
        self.assertEqual(summary["automatic_catalog_insertions"], 0)
        self.assertEqual(summary["database_writes"], 0)


if __name__ == "__main__":
    unittest.main()
