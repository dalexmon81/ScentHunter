from app.services.identity_scope import identity_scope


class Matcher:
    def build_identity_scope(self, query):
        return ["identity", query]


def test_prefers_identity_scope_contract():
    assert identity_scope("Dior", Matcher()) == ["identity", "Dior"]


class LegacyMatcher:
    def build_query_scope(self, query):
        return ["legacy", query]


def test_supports_legacy_query_scope_contract():
    assert identity_scope("Chanel", LegacyMatcher()) == ["legacy", "Chanel"]


class BrokenMatcher:
    def build_identity_scope(self, query):
        raise RuntimeError("broken")


def test_matcher_failure_fails_closed():
    assert identity_scope("Dior", BrokenMatcher(), logger=lambda message: None) == []


def test_missing_matcher_returns_empty_scope():
    assert identity_scope("Dior", None) == []
