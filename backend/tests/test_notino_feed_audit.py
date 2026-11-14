import tempfile
import unittest
from pathlib import Path

from backend.scripts.audit_notino_cj_feed import audit_feed


class NotinoFeedAuditTests(unittest.TestCase):
    def test_counts_perfumes_rejected_gtins_and_duplicate_identifiers(self):
        xml = """<?xml version="1.0"?>
        <feed>
          <entry>
            <id>A</id><title>Perfume A</title>
            <google_product_category>479</google_product_category>
            <brand>Brand A</brand><gtin>123456789012</gtin>
            <price>10 EUR</price><availability>in stock</availability>
            <link>https://example.test/a</link><sale_price>9 EUR</sale_price>
          </entry>
          <entry>
            <id>B</id><title>Perfume B</title>
            <google_product_category>479</google_product_category>
            <brand>Brand A</brand><gtin>123456789012</gtin>
            <price>11 EUR</price><availability>out of stock</availability>
            <link>https://example.test/b</link>
          </entry>
          <entry>
            <id>C</id><title>Bad identifier</title>
            <google_product_category>479</google_product_category>
            <brand>Brand B</brand><gtin>1234567890</gtin>
            <price>12 EUR</price><availability>in stock</availability>
            <link>https://example.test/c</link>
          </entry>
          <entry>
            <id>D</id><title>Not perfume</title>
            <google_product_category>123</google_product_category>
          </entry>
        </feed>"""

        with tempfile.TemporaryDirectory() as directory:
            feed = Path(directory) / "feed.xml"
            feed.write_text(xml, encoding="utf-8")
            report = audit_feed(feed)

        summary = report["summary"]
        self.assertEqual(summary["entries"], 4)
        self.assertEqual(summary["perfume_entries"], 3)
        self.assertEqual(summary["accepted_gtin_length"], 2)
        self.assertEqual(summary["rejected_gtin_length"], 1)
        self.assertEqual(summary["unique_accepted_gtins"], 1)
        self.assertEqual(summary["duplicate_gtin_values"], 1)
        self.assertEqual(summary["sale_price_entries"], 1)
        self.assertEqual(report["duplicate_gtins"][0]["gtin"], "123456789012")
        self.assertIn("check digit", report["policy_note"])


if __name__ == "__main__":
    unittest.main()
