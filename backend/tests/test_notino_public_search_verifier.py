import unittest
from urllib.parse import parse_qs, urlsplit

from scripts.verify_notino_public_search import _phase2_brand_offers, poll_public_search


JOB_ID = "0123456789abcdef0123456789abcdef"


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class PublicNotinoSearchPollingTests(unittest.TestCase):
    def poll(self, responses, timeout=60):
        clock = FakeClock()
        progress = []

        def request(_base, path, _deadline):
            parsed = urlsplit(path)
            if parsed.path == "/search-start":
                self.assertEqual(
                    parse_qs(parsed.query),
                    {"q": ["Lattafa"], "store": ["notino"]},
                )
            else:
                self.assertEqual(parsed.path, "/search-status")
                self.assertEqual(parse_qs(parsed.query), {"job_id": [JOB_ID]})
            if not responses:
                raise AssertionError("unexpected extra request")
            return responses.pop(0)

        result = poll_public_search(
            "Lattafa",
            "https://staging.example",
            overall_deadline=timeout,
            search_timeout=timeout,
            request_json=request,
            clock=clock,
            sleep=clock.sleep,
            progress=lambda *args: progress.append(args),
        )
        return result, clock, progress

    def test_polls_intermediate_searching_until_real_completion(self):
        result, clock, progress = self.poll([
            {"job_id": JOB_ID, "status": "searching", "completed": False},
            {"job_id": JOB_ID, "status": "searching", "completed": False},
            {"job_id": JOB_ID, "status": "completed", "completed": True, "errors": {}},
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(clock.value, 1.0)
        self.assertTrue(any(item[2] == "searching" for item in progress))
        self.assertEqual(progress[-1][2], "completed")

    def test_retries_busy_start_without_accepting_missing_job_id(self):
        clock = FakeClock()
        requests = [
            {"status": "busy", "completed": False, "retry_after_ms": 100},
            {"job_id": JOB_ID, "status": "searching", "completed": False},
            {"job_id": JOB_ID, "status": "completed", "completed": True, "errors": {}},
        ]

        def request(_base, path, _deadline):
            if urlsplit(path).path == "/search-status":
                self.assertEqual(parse_qs(urlsplit(path).query), {"job_id": [JOB_ID]})
            return requests.pop(0)

        result = poll_public_search(
            "Lattafa",
            "https://staging.example",
            overall_deadline=10,
            request_json=request,
            clock=clock,
            sleep=clock.sleep,
            progress=lambda *_args: None,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(clock.value, 0.6)

    def test_rejects_missing_or_invalid_job_ids(self):
        for payload in (
            {"status": "searching", "completed": False},
            {"job_id": "not-a-job", "status": "searching", "completed": False},
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(RuntimeError, "job_id"):
                    self.poll([payload])

    def test_reports_terminal_error_states(self):
        for payload in (
            {
                "job_id": JOB_ID,
                "status": "error",
                "completed": True,
                "errors": {"job": "worker failed"},
            },
            {
                "job_id": JOB_ID,
                "status": "completed_with_store_issues",
                "completed": True,
                "errors": {},
            },
            {
                "job_id": JOB_ID,
                "status": "completed",
                "completed": True,
                "errors": {"job": "job_not_found"},
            },
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(RuntimeError, "terminal state"):
                    self.poll([payload])

    def test_timeout_is_not_returned_as_an_empty_result(self):
        clock = FakeClock()
        responses = [{"job_id": JOB_ID, "status": "searching", "completed": False}]

        def request(_base, _path, _deadline):
            if responses:
                return responses.pop(0)
            return {"job_id": JOB_ID, "status": "searching", "completed": False}

        with self.assertRaisesRegex(TimeoutError, "status='searching'"):
            poll_public_search(
                "Lattafa",
                "https://staging.example",
                overall_deadline=1,
                search_timeout=1,
                request_json=request,
                clock=clock,
                sleep=clock.sleep,
                progress=lambda *_args: None,
            )

    def test_rejects_mismatched_status_job_id(self):
        with self.assertRaisesRegex(RuntimeError, "wrong job"):
            self.poll([
                {"job_id": JOB_ID, "status": "searching", "completed": False},
                {
                    "job_id": "fedcba9876543210fedcba9876543210",
                    "status": "completed",
                    "completed": True,
                },
            ])

    def test_brand_verification_ignores_legacy_rows(self):
        payload = {
            "results": [{
                "offers": [
                    {"store": "Notino", "brand": "Armaf", "source": "legacy"},
                    {
                        "store": "Notino",
                        "brand": "Armaf",
                        "source": "cj_notino_fr_feed",
                    },
                    {
                        "store": "Notino",
                        "brand": "Lattafa",
                        "source": "cj_notino_fr_feed",
                    },
                ],
            }],
        }
        self.assertEqual(
            _phase2_brand_offers(payload, "armaf"),
            [payload["results"][0]["offers"][1]],
        )


if __name__ == "__main__":
    unittest.main()
