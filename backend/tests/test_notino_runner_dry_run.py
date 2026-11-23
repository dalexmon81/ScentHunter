import base64
import hashlib
import io
import time
import unittest
from unittest.mock import patch

from scripts import notino_cj_runner_dry_run as dry_run


ITEM = b"""<item><id>one</id><title>Perfume</title><brand>Brand</brand>
<price>20 EUR</price><availability>in stock</availability>
<link>https://www.notino.fr/brand/product/</link></item>"""
INVALID = ITEM.replace(b"20 EUR", b"0 EUR")
SAMPLE = b"<rss><channel>" + ITEM + ITEM + INVALID + b"</channel></rss>"


class NotinoRunnerDryRunTests(unittest.TestCase):
    def test_stages_valid_offers_without_duplicates(self):
        result = dry_run.stage_feed(io.BytesIO(SAMPLE), len(SAMPLE), time.monotonic(), require_reviewed_gtins=False)
        self.assertEqual(result["parser_stats"]["products_read"], 3)
        self.assertEqual(result["parser_stats"]["valid_items"], 2)
        self.assertEqual(result["parser_stats"]["rejected_items"], 1)
        self.assertEqual(result["staged_unique_variants"], 1)
        self.assertEqual(result["duplicate_items"], 1)
        self.assertFalse(result["catalog_database_touched"])

    def test_malformed_xml_does_not_produce_success(self):
        with self.assertRaisesRegex(dry_run.feed.FeedImportError, "notino_feed_invalid_xml"):
            dry_run.stage_feed(io.BytesIO(SAMPLE[:-10]), len(SAMPLE), time.monotonic())

    def test_transfer_requires_matching_size_and_digest(self):
        def fake_run(*args, stdout, **kwargs):
            stdout.write(
                dry_run.START + base64.b64encode(SAMPLE) + b"\n"
                + dry_run.END + str(len(SAMPLE)).encode() + b":"
                + hashlib.sha256(SAMPLE).hexdigest().encode() + b"\n"
            )
            return type("Result", (), {"returncode": 0})()

        with patch.object(dry_run.subprocess, "run", side_effect=fake_run):
            target = io.BytesIO()
            self.assertEqual(dry_run.download_from_fly(target), len(SAMPLE))
            self.assertEqual(target.read(), SAMPLE)

        def corrupted(*args, stdout, **kwargs):
            stdout.write(dry_run.START + base64.b64encode(SAMPLE) + b"\n" + dry_run.END + b"1:bad\n")
            return type("Result", (), {"returncode": 0})()

        with patch.object(dry_run.subprocess, "run", side_effect=corrupted):
            with self.assertRaisesRegex(RuntimeError, "fly_feed_transfer_integrity_failed"):
                dry_run.download_from_fly(io.BytesIO())


if __name__ == "__main__":
    unittest.main()
