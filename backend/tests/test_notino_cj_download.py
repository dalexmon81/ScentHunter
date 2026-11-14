from __future__ import annotations

import base64
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.download_notino_cj_feed import build_download_url, download_feed


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _zip_bytes(member_name="NOTINO_fr-NotinoFR_google_all-shopping.xml"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, "<rss><channel><item /></channel></rss>")
    return buffer.getvalue()


class NotinoCJDownloadTests(unittest.TestCase):
    def test_builds_expected_subscription_url(self):
        self.assertEqual(
            build_download_url(),
            "https://datatransfer.cj.com/datatransfer/files/8115142/"
            "outgoing/productcatalog/324587/NOTINO_fr-NotinoFR_google_all-shopping.xml.zip",
        )

    def test_downloads_zip_with_basic_auth_and_atomically_extracts_one_xml(self):
        payload = _zip_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "scripts.download_notino_cj_feed.urllib.request.urlopen",
                return_value=FakeResponse(payload),
            ) as mocked:
                result = download_feed(
                    tmp, username="8115142", password="test-secret",
                )
            request = mocked.call_args.args[0]
            expected = base64.b64encode(b"8115142:test-secret").decode("ascii")
            self.assertEqual(request.get_header("Authorization"), f"Basic {expected}")
            self.assertEqual(result.name, "NOTINO_fr-NotinoFR_google_all-shopping.xml")
            self.assertEqual(result.read_text(encoding="utf-8"), "<rss><channel><item /></channel></rss>")
            self.assertEqual(list(Path(tmp).iterdir()), [result])

    def test_rejects_missing_credentials_and_non_zip_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                download_feed(tmp, username="", password="")
            with patch(
                "scripts.download_notino_cj_feed.urllib.request.urlopen",
                return_value=FakeResponse(b"not a zip"),
            ):
                with self.assertRaises(ValueError):
                    download_feed(tmp, username="8115142", password="test-secret")
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
