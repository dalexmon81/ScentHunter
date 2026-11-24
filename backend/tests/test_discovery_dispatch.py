from __future__ import annotations

import unittest
from unittest.mock import Mock
from uuid import uuid4

from app.connectors.base import DiscoveredProduct
from app.discovery.dispatch import dispatch_discovered_products


class DiscoveryDispatchTests(unittest.TestCase):
    def setUp(self):
        self.store_id = uuid4()
        self.products = (
            DiscoveredProduct("sku-1", "https://shop.example/p/1"),
            DiscoveredProduct("sku-2", "https://shop.example/p/2"),
        )

    def test_dispatches_every_candidate_and_schedules_next_page(self):
        fetch = Mock()
        next_page = Mock()
        result = dispatch_discovered_products(
            self.store_id, self.products, cursor="20", limit=2,
            enqueue_fetch=fetch, enqueue_next_page=next_page,
        )
        self.assertEqual(result.fetch_jobs_queued, 2)
        self.assertEqual(result.next_cursor, "22")
        self.assertEqual(result.errors, ())
        self.assertEqual(fetch.call_count, 2)
        fetch.assert_any_call(self.store_id, "sku-1")
        fetch.assert_any_call(self.store_id, "sku-2")
        next_page.assert_called_once_with(self.store_id, cursor="22", limit=2)

    def test_failed_candidate_is_reported_without_blocking_other_candidates(self):
        def enqueue(store_id, external_id):
            if external_id == "sku-1":
                raise RuntimeError("queue unavailable")
        result = dispatch_discovered_products(
            self.store_id, self.products, cursor=None, limit=10,
            enqueue_fetch=enqueue, enqueue_next_page=Mock(),
        )
        self.assertEqual(result.fetch_jobs_queued, 1)
        self.assertIsNone(result.next_cursor)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("sku-1", result.errors[0])
        self.assertIn("queue unavailable", result.errors[0])

    def test_failed_next_page_is_reported_and_cursor_is_preserved(self):
        result = dispatch_discovered_products(
            self.store_id, self.products, cursor=None, limit=2,
            enqueue_fetch=Mock(),
            enqueue_next_page=Mock(side_effect=RuntimeError("queue down")),
        )
        self.assertEqual(result.next_cursor, "2")
        self.assertEqual(result.fetch_jobs_queued, 2)
        self.assertIn("enqueue_next_page:RuntimeError:queue down", result.errors)

    def test_rejects_invalid_page_size_and_cursor(self):
        for limit in (0, 1001, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                dispatch_discovered_products(
                    self.store_id, self.products, cursor=None, limit=limit,
                    enqueue_fetch=Mock(), enqueue_next_page=Mock(),
                )
        with self.assertRaisesRegex(ValueError, "cursor"):
            dispatch_discovered_products(
                self.store_id, self.products, cursor="-1", limit=10,
                enqueue_fetch=Mock(), enqueue_next_page=Mock(),
            )


if __name__ == "__main__":
    unittest.main()
