import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal

from backend.connectors.notino_cj import parse_entry


class NotinoCJConnectorTests(unittest.TestCase):
    def test_parses_perfume_offer(self):
        entry = ET.fromstring("""
        <entry>
          <id>TEST_EDP100</id><title>Test Eau de Parfum 100 ml</title>
          <google_product_category>479</google_product_category>
          <brand>Test Brand</brand><gtin>123456789012</gtin>
          <price>49.90 EUR</price><sale_price>39.90 EUR</sale_price>
          <availability>in stock</availability>
          <link>https://example.com/affiliate</link>
          <image_link>https://example.com/image.jpg</image_link>
          <size>100 ml</size><gender>unisex</gender>
          <product_type>Parfums</product_type>
          <last_updated>2026-11-10T02:43:11-08:00</last_updated>
        </entry>
        """)
        offer = parse_entry(entry)
        self.assertEqual(offer.store, "NOTINO.fr")
        self.assertEqual(offer.gtin, "123456789012")
        self.assertEqual(offer.price, Decimal("49.90"))
        self.assertEqual(offer.sale_price, Decimal("39.90"))
        self.assertEqual(offer.currency, "EUR")

    def test_rejects_gtin_with_invalid_gs1_check_digit(self):
        entry = ET.fromstring("""
        <entry><id>BAD_GTIN</id><google_product_category>479</google_product_category>
        <gtin>123456789013</gtin><price>10 EUR</price>
        <availability>in stock</availability><link>https://example.com</link></entry>
        """)
        with self.assertRaisesRegex(ValueError, "check digit"):
            parse_entry(entry)

    def test_skips_non_perfume(self):
        entry = ET.fromstring("<entry><google_product_category>123</google_product_category></entry>")
        self.assertIsNone(parse_entry(entry))

    def test_rejects_missing_gtin(self):
        entry = ET.fromstring("""
        <entry><google_product_category>479</google_product_category>
        <price>10 EUR</price><link>https://example.com</link></entry>
        """)
        with self.assertRaises(ValueError):
            parse_entry(entry)


if __name__ == "__main__":
    unittest.main()
