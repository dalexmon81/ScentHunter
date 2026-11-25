from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "check_bplatz_live_discovery_readonly.py"
sys.path.insert(0, str(BACKEND))

SPEC = importlib.util.spec_from_file_location("bplatz_live_discovery_probe", SCRIPT)
PROBE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(PROBE)


class BplatzLiveDiscoveryProbeTests(unittest.TestCase):
    def test_empty_html_is_reported_without_calling_parser(self):
        response = Mock()
        response.url = "https://en.bplatz.de/products/liquid-brun"
        response.status_code = 200
        response.content = b""
        response.text = ""
        response.headers = {"Content-Type": "text/html"}
        response.close = Mock()

        session = Mock()
        session.get.return_value = response

        result = PROBE.fetch_candidate(
            session, "https://en.bplatz.de/products/liquid-brun"
        )

        self.assertEqual(result["fetch_status"], "empty_body")
        self.assertEqual(result["html_bytes"], 0)
        self.assertIsNone(result["parsed"])
        response.close.assert_called_once()

    def test_http_429_is_reported_and_not_parsed(self):
        response = Mock()
        response.url = "https://en.bplatz.de/products/liquid-brun"
        response.status_code = 429
        response.content = b"rate limited"
        response.text = "rate limited"
        response.headers = {"Content-Type": "text/html"}
        response.close = Mock()

        session = Mock()
        session.get.return_value = response

        with patch.object(PROBE, "parse_product_html") as parser:
            result = PROBE.fetch_candidate(
                session, "https://en.bplatz.de/products/liquid-brun"
            )

        self.assertEqual(result["fetch_status"], "http_error")
        self.assertEqual(result["http_status_label"], "http_429_rate_limited")
        parser.assert_not_called()
        response.close.assert_called_once()

    def test_http_403_and_404_have_distinct_labels(self):
        for status, expected in (
            (403, "http_403_forbidden"),
            (404, "http_404_not_found"),
        ):
            response = Mock()
            response.url = "https://en.bplatz.de/products/liquid-brun"
            response.status_code = status
            response.content = b"denied"
            response.headers = {"Content-Type": "text/html"}
            response.close = Mock()
            session = Mock()
            session.get.return_value = response

            result = PROBE.fetch_candidate(
                session, "https://en.bplatz.de/products/liquid-brun"
            )
            self.assertEqual(result["http_status_label"], expected)
            self.assertEqual(result["fetch_status"], "http_error")

    def test_parser_exception_is_reported_instead_of_hidden(self):
        response = Mock()
        response.url = "https://en.bplatz.de/products/liquid-brun"
        response.status_code = 200
        response.content = b"<html><h1>Liquid Brun</h1></html>"
        response.text = "<html><h1>Liquid Brun</h1></html>"
        response.headers = {"Content-Type": "text/html"}
        response.close = Mock()
        session = Mock()
        session.get.return_value = response

        with patch.object(PROBE, "parse_product_html", side_effect=TypeError("bad HTML")):
            result = PROBE.fetch_candidate(
                session, "https://en.bplatz.de/products/liquid-brun"
            )

        self.assertEqual(result["fetch_status"], "parse_error")
        self.assertIn("TypeError: bad HTML", result["fetch_error"])
        response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
