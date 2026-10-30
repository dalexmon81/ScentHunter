import unittest
from decimal import Decimal
from unittest.mock import patch

from backend.offer_engine.contracts import Availability, OfferObservation, RetailerListing, Verification
from backend.offer_engine.runner import OfferEngineRunner


class FakeConnector:
    def __init__(self, retailer, listings=None, discovery_error=None, observe_error=None):
        self.retailer = retailer
        self._listings = listings or []
        self.discovery_error = discovery_error
        self.observe_error = observe_error

    def discover(self, query):
        if self.discovery_error:
            raise self.discovery_error
        return self._listings

    def observe(self, listing):
        if self.observe_error:
            raise self.observe_error
        return OfferObservation.now(
            listing_key=f"{self.retailer}:{listing.external_id}",
            price=Decimal("20.00"),
            currency="EUR",
            availability=Availability.IN_STOCK,
            source="product_page",
            verification=Verification.UNVERIFIED,
            evidence_url=listing.product_url,
            evidence_hash="sha256:test",
        )

    def healthcheck(self):
        raise NotImplementedError


class FakeRepository:
    def __init__(self):
        self.records = []

    def record(self, listing, observation):
        self.records.append((listing, observation))
        return {"published": False}


def listing(sku):
    return RetailerListing(
        retailer="deloox",
        external_id=sku,
        product_url=f"https://www.deloox.be/p/{sku}",
        raw_title=f"Perfume {sku}",
        raw_size_ml=100,
        market="BE",
    )


class OfferEngineRunnerTests(unittest.TestCase):
    def test_discovery_failure_does_not_stop_other_retailers(self):
        healthy = FakeConnector("healthy", [listing("ok", retailer="healthy")])
        broken = FakeConnector("broken", discovery_error=RuntimeError("blocked"))
        repositories = {}

        def repository_factory(connector):
            repositories[connector.retailer] = FakeRepository()
            return repositories[connector.retailer]

        runner = OfferEngineRunner(matcher=object(), repository_factory=repository_factory)
        with patch(
            "backend.offer_engine.runner.resolve_observation",
            side_effect=lambda listing, observation, matcher: type(
                "Resolution", (), {"status": "unresolved", "observation": observation}
            )(),
        ):
            result = runner.run([broken, healthy], "perfume")

        self.assertEqual([item.status for item in result.connectors], ["failed", "success"])
        self.assertEqual(result.listings_seen, 1)
        self.assertEqual(result.observations_written, 1)
        self.assertEqual(len(repositories["healthy"].records), 1)
        self.assertIn("blocked", result.connectors[0].errors[0])

    def test_one_listing_failure_marks_connector_partial_and_keeps_going(self):
        first = listing("one")
        second = listing("two")
        connector = FakeConnector("deloox", [first, second])
        repository = FakeRepository()
        runner = OfferEngineRunner(matcher=object(), repository_factory=lambda _: repository)
        calls = {"count": 0}

        def resolve(item, observation, matcher):
            calls["count"] += 1
            if calls["count"] == 1:
                raise ValueError("bad identity")
            return type("Resolution", (), {"status": "unresolved", "observation": observation})()

        with patch("backend.offer_engine.runner.resolve_observation", side_effect=resolve):
            result = runner.run([connector], "perfume")

        self.assertEqual(result.connectors[0].status, "partial")
        self.assertEqual(result.connectors[0].listings_seen, 2)
        self.assertEqual(result.connectors[0].observations_written, 1)
        self.assertEqual(len(repository.records), 1)

    def test_all_listing_failures_mark_connector_failed(self):
        connector = FakeConnector("deloox", [listing("one")], observe_error=RuntimeError("timeout"))
        runner = OfferEngineRunner(matcher=object(), repository_factory=lambda _: FakeRepository())
        result = runner.run([connector], "perfume")
        self.assertEqual(result.connectors[0].status, "failed")
        self.assertEqual(result.connectors[0].observations_written, 0)


if __name__ == "__main__":
    unittest.main()
