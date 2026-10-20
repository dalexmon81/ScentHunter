import unittest
from unittest.mock import Mock

import requests

from scenthunter_next_engine.adapters.deloox import DelooxProductPageAdapter
from scenthunter_next_engine.errors import AdapterFailure, ErrorKind

URL = "https://www.deloox.nl/product/12345/test"


class DelooxFetchTests(unittest.TestCase):
    def adapter_with_response(self, status, *, url=URL, content=b"<html>ok</html>", headers=None):
        response = Mock()
        response.status_code = status
        response.url = url
        response.content = content
        response.headers = headers or {}
        session = Mock()
        session.get.return_value = response
        return DelooxProductPageAdapter(session=session), session

    def test_fetch_passes_timeout_and_headers(self):
        adapter, session = self.adapter_with_response(200)
        self.assertEqual(adapter.fetch(URL), b"<html>ok</html>")
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["timeout"], (3.5, 8.0))
        self.assertTrue(kwargs["allow_redirects"])
        self.assertIn("User-Agent", kwargs["headers"])

    def test_fetch_classifies_forbidden_without_retrying(self):
        adapter, session = self.adapter_with_response(403)
        with self.assertRaises(AdapterFailure) as caught:
            adapter.fetch(URL)
        self.assertEqual(caught.exception.kind, ErrorKind.ACCESS_DENIED)
        session.get.assert_called_once()

    def test_fetch_classifies_rate_limit_and_retry_after(self):
        adapter, _ = self.adapter_with_response(429, headers={"Retry-After": "17"})
        with self.assertRaises(AdapterFailure) as caught:
            adapter.fetch(URL)
        self.assertEqual(caught.exception.kind, ErrorKind.RATE_LIMITED)
        self.assertEqual(caught.exception.retry_after_seconds, 17.0)

    def test_fetch_classifies_not_found_and_upstream_errors(self):
        for status, expected in ((404, ErrorKind.NOT_FOUND), (410, ErrorKind.NOT_FOUND),
                                 (503, ErrorKind.UPSTREAM_SERVER)):
            with self.subTest(status=status):
                adapter, _ = self.adapter_with_response(status)
                with self.assertRaises(AdapterFailure) as caught:
                    adapter.fetch(URL)
                self.assertEqual(caught.exception.kind, expected)

    def test_fetch_rejects_redirect_to_untrusted_host(self):
        adapter, _ = self.adapter_with_response(200, url="https://example.com/product/12345")
        with self.assertRaises(AdapterFailure) as caught:
            adapter.fetch(URL)
        self.assertEqual(caught.exception.kind, ErrorKind.INVALID_URL)

    def test_fetch_rejects_empty_body(self):
        adapter, _ = self.adapter_with_response(200, content=b"")
        with self.assertRaises(AdapterFailure) as caught:
            adapter.fetch(URL)
        self.assertEqual(caught.exception.kind, ErrorKind.INVALID_DOCUMENT)

    def test_fetch_classifies_timeout_as_transient(self):
        session = Mock()
        session.get.side_effect = requests.Timeout("read timeout")
        adapter = DelooxProductPageAdapter(session=session)
        with self.assertRaises(AdapterFailure) as caught:
            adapter.fetch(URL)
        self.assertEqual(caught.exception.kind, ErrorKind.TRANSIENT_NETWORK)

    def test_failed_parse_does_not_reuse_previous_redirect_target(self):
        adapter = DelooxProductPageAdapter()
        adapter._request_state.final_url = "https://www.deloox.nl/product/67890/previous"
        with self.assertRaises(AdapterFailure):
            adapter.parse(URL, b"<html><body><h1>broken page</h1></body></html>")
        self.assertIsNone(adapter._request_state.final_url)


if __name__ == "__main__":
    unittest.main()
