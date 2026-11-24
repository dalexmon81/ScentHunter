from __future__ import annotations

import subprocess
import sys
import unittest

from app.connectors.notino_links import validated_cj_offer_url


class NotinoLinkBoundaryTests(unittest.TestCase):
    def test_legacy_feed_module_reexports_the_same_url_validator(self):
        from scrapers.notino.affiliate_feed import validated_cj_offer_url as legacy_validator
        self.assertIs(legacy_validator, validated_cj_offer_url)

    def test_pure_link_import_does_not_eagerly_import_retailer_scraper(self):
        code = (
            "import sys; "
            "import app.connectors.notino_links; "
            "assert 'scrapers.notino.affiliate_feed' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
