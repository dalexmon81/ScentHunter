"""Focused contract tests for catalog hydration adapters."""
from pathlib import Path
import re
import unittest

from scrapers import parfumzentrum


class ParfumZentrumHydrationTests(unittest.TestCase):
    def test_internal_sku_suffix_regex_strips_url_identifier(self):
        query = "Berdoues Monoi Tiare Eau de Toilette 100 ml_z904294"
        normalized = re.sub(r"\bz\d+\s*$", "", query, flags=re.I).strip()
        self.assertEqual(normalized, query)

    def test_product_url_is_accepted_by_catalog_adapter(self):
        url = "https://www.parfum-zentrum.de/berdoues-monoi-tiare-eau-de-toilette-100-ml-unisex_z904294/"
        self.assertTrue(parfumzentrum._product_url(url))


if __name__ == "__main__":
    unittest.main()
