from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_notino_core_feed_csv import export_core_feed


class NotinoCoreFeedExportTests(unittest.TestCase):
    def test_exports_only_core_fragrances_and_flags_invalid_and_duplicate_gtins(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss xmlns:g="http://base.google.com/ns/1.0"><channel>
          <entry>
            <g:id>SKU-1</g:id><g:title>Known Eau de Parfum 100 ml pour homme</g:title>
            <g:brand>Known</g:brand><g:gtin>4006381333931</g:gtin>
            <g:price>49.90 EUR</g:price><g:sale_price>39.90 EUR</g:sale_price>
            <g:availability>in stock</g:availability><g:size>100 ml</g:size>
            <g:product_type>Beauty &gt; parfémované vody</g:product_type>
            <g:item_group_id>GROUP-1</g:item_group_id><g:link>https://notino.fr/p/sku-1</g:link>
            <g:last_updated>2026-11-10T12:00:00Z</g:last_updated>
          </entry>
          <entry>
            <g:id>SKU-2</g:id><g:title>Known Eau de Parfum 100 ml pour homme second listing</g:title>
            <g:brand>Known</g:brand><g:gtin>4006381333931</g:gtin>
            <g:price>50.00 EUR</g:price><g:availability>out of stock</g:availability>
            <g:size>100 ml</g:size><g:product_type>Beauty &gt; parfémované vody</g:product_type>
            <g:link>https://notino.fr/p/sku-2</g:link>
          </entry>
          <entry>
            <g:id>SKU-BAD</g:id><g:title>Bad GTIN EDP 50 ml</g:title>
            <g:brand>Other</g:brand><g:gtin>4006381333932</g:gtin>
            <g:price>10.00 EUR</g:price><g:availability>in stock</g:availability>
            <g:product_type>Beauty &gt; parfémované vody</g:product_type>
          </entry>
          <entry>
            <g:id>GIFT-1</g:id><g:title>Gift set</g:title><g:brand>Known</g:brand>
            <g:gtin>4006381333931</g:gtin><g:product_type>Beauty &gt; gift sets</g:product_type>
          </entry>
        </channel></rss>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.xml"
            path.write_text(xml, encoding="utf-8")
            rows, summary = export_core_feed(path)
        self.assertEqual({row["id"] for row in rows}, {"SKU-1", "SKU-2", "SKU-BAD"})
        self.assertEqual(summary["core_fragrance_products"], 3)
        self.assertEqual(summary["valid_gtin_rows"], 2)
        self.assertEqual(summary["invalid_gtin_rows"], 1)
        self.assertEqual(summary["duplicate_gtin_rows"], 2)
        self.assertTrue(rows[0]["normalized_brand"])
        self.assertEqual(summary["database_writes"], 0)
        self.assertEqual(summary["catalog_writes"], 0)


if __name__ == "__main__":
    unittest.main()
