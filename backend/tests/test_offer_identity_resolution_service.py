from app.services.offer_identity_resolution import resolve_offer_identity


class Matcher:
    def __init__(self, result):
        self.result = result
        self.seen = None

    def match(self, offer, query):
        self.seen = (offer, query)
        return self.result


def normalize_store(value, fallback=""):
    return str(value or fallback).strip().lower()


LABELS = {"sabina": "Sabina", "deloox": "Deloox"}


def test_missing_matcher_fails_closed():
    result = resolve_offer_identity({"name": "Perfume"}, "Perfume", None, LABELS, normalize_store)
    assert result["_match_status"] == "unresolved"
    assert result["catalog_id"] is None


def test_matcher_result_is_exposed_as_canonical_identity():
    matcher = Matcher({"catalog_id": "canonical-1", "canonical_name": "Perfume", "confidence": 0.99})
    source = {"name": "Retailer title", "brand": "Brand", "store": "sabina"}
    result = resolve_offer_identity(source, "Perfume", matcher, LABELS, normalize_store)
    assert result["_match_status"] == "matched"
    assert result["catalog_id"] == "canonical-1"
    assert result["canonical_name"] == "Perfume"
    assert result["match_confidence"] == 0.99
    assert source["name"] == "Retailer title"


def test_matcher_exception_returns_unresolved_with_error():
    class Broken:
        def match(self, offer, query):
            raise RuntimeError("matcher unavailable")
    result = resolve_offer_identity({"name": "Perfume"}, "Perfume", Broken(), LABELS, normalize_store,
                                    logger=lambda message: None)
    assert result["_match_status"] == "unresolved"
    assert "matcher unavailable" in result["_match_error"]


def test_none_match_rejection_reason_is_preserved():
    class Rejecting:
        def match(self, offer, query):
            return None
        def rejection_reason(self, offer):
            return "non_fragrance"
    result = resolve_offer_identity({"name": "Gift set"}, "Gift set", Rejecting(), LABELS, normalize_store)
    assert result["_match_status"] == "rejected"
    assert result["_reject_reason"] == "non_fragrance"


def test_missing_catalog_id_downgrades_match():
    matcher = Matcher({"canonical_name": "Perfume"})
    result = resolve_offer_identity({"name": "Perfume"}, "Perfume", matcher, LABELS, normalize_store)
    assert result["_match_status"] == "unresolved"


def test_logger_failure_does_not_break_fail_closed_match_result():
    class Broken:
        def match(self, offer, query):
            raise RuntimeError("matcher unavailable")

    def broken_logger(message):
        raise RuntimeError("logger unavailable")

    result = resolve_offer_identity(
        {"name": "Perfume"},
        "Perfume",
        Broken(),
        LABELS,
        normalize_store,
        logger=broken_logger,
    )
    assert result["_match_status"] == "unresolved"
    assert "matcher unavailable" in result["_match_error"]
