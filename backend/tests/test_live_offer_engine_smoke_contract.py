from __future__ import annotations

import unittest

from backend.offer_engine.live_offer_engine_smoke import result_exit_code


class LiveOfferEngineSmokeContractTests(unittest.TestCase):
    def test_retailer_warnings_remain_a_reviewable_partial_success(self) -> None:
        result = {
            "status": "success_with_warnings",
            "retailer_warnings": [
                {"retailer": "notino", "status": "not_configured"}
            ],
        }
        self.assertEqual(result_exit_code(result), 0)

    def test_clean_success_passes(self) -> None:
        self.assertEqual(result_exit_code({"status": "success"}), 0)

    def test_explicit_failure_fails(self) -> None:
        self.assertEqual(result_exit_code({"status": "failed"}), 1)


if __name__ == "__main__":
    unittest.main()
