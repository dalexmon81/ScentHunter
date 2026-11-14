import csv
import json
import tempfile
import unittest
from pathlib import Path

from backend.scripts.audit_notino_catalog_coverage import audit_coverage


class NotinoCatalogCoverageTests(unittest.TestCase):
    def test_distinguishes_missing_brands_from_name_gaps(self):
        xml = """<?xml version="1.0"?>
        <feed>
          <entry>
            <id>KNOWN-MATCH</id><brand>Dior</brand><gtin>8011003809202</gtin>
            <product_type>Parfémy &gt; Toaletní vody</product_type>
            <google_product_category>479</google_product_category>
          </entry>
          <entry>
            <id>KNOWN-NOMATCH</id><brand>Dior</brand><gtin>8011003809219</gtin>
            <product_type>Parfémy &gt; Parfémované vody</product_type>
            <google_product_category>479</google_product_category>
          </entry>
          <entry>
            <id>MISSING-BRAND</id><brand>Nishane</brand><gtin>8681008055070</gtin>
            <product_type>Parfémy &gt; Parfémy</product_type>
            <google_product_category>479</google_product_category>
          </entry>
        </feed>"""
        catalog = {
            "products": [{"product_id": "P1", "brand_name": "Dior"}],
            "variants": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feed = root / "feed.xml"
            catalog_path = root / "catalog.json"
            candidates = root / "candidates.csv"
            feed.write_text(xml, encoding="utf-8")
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            with candidates.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["feed_external_id", "review_status", "confidence_band", "candidate_scope"])
                writer.writeheader()
                writer.writerow({"feed_external_id": "KNOWN-MATCH", "review_status": "needs_human_review", "confidence_band": "review_high", "candidate_scope": "variant"})
            rows = audit_coverage(feed, catalog_path, candidates)
        by_brand = {row["feed_brand"]: row for row in rows}
        self.assertTrue(by_brand["Dior"]["catalog_brand_present"])
        self.assertEqual(by_brand["Dior"]["candidate_products"], 1)
        self.assertEqual(by_brand["Dior"]["no_candidate_products"], 1)
        self.assertEqual(by_brand["Dior"]["strong_variant_candidates"], 1)
        self.assertFalse(by_brand["Nishane"]["catalog_brand_present"])
        self.assertEqual(by_brand["Nishane"]["catalog_coverage_status"], "brand_not_in_catalog")

    def test_excludes_non_core_product_types(self):
        xml = """<feed>
          <entry><id>CORE</id><brand>Dior</brand><gtin>8011003809202</gtin><product_type>Parfémy &gt; Toaletní vody</product_type><google_product_category>479</google_product_category></entry>
          <entry><id>GIFT</id><brand>Dior</brand><gtin>8011003809202</gtin><product_type>Parfémy &gt; Dárkové sady</product_type><google_product_category>479</google_product_category></entry>
        </feed>"""
        catalog = {"products": [{"product_id": "P1", "brand_name": "Dior"}], "variants": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "feed.xml").write_text(xml, encoding="utf-8")
            (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
            rows = audit_coverage(root / "feed.xml", root / "catalog.json")
        self.assertEqual(rows[0]["feed_products"], 1)


if __name__ == "__main__":
    unittest.main()
