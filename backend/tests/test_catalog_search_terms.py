from app.services.catalog_search_terms import catalog_search_terms


class Matcher:
    def __init__(self, terms):
        self.terms = terms

    def catalog_search_terms(self, query):
        return self.terms


def test_search_terms_keep_original_query_first_and_dedupe():
    result = catalog_search_terms("Hawas", Matcher(["Hawas", "Hawas Ice", "Hawas Ice"]))
    assert result[0] == "Hawas"
    assert result.count("Hawas Ice") == 1


def test_single_token_family_search_keeps_aliases_without_token_overlap():
    result = catalog_search_terms("Hawas", Matcher(["Kobra For Him", "Hawas Ice"]))
    assert "Kobra For Him" in result
    assert "Hawas Ice" in result


def test_multi_token_search_requires_lexical_overlap():
    result = catalog_search_terms("Liquid Brun", Matcher([
        "Liquid Brun Limited Edition",
        "Kobra For Him",
        "Liquid Gold",
    ]))
    assert "Liquid Brun Limited Edition" in result
    assert "Kobra For Him" not in result
    assert "Liquid Gold" in result


def test_search_terms_without_matcher_return_original_query():
    assert catalog_search_terms("Dior Sauvage", None) == ["Dior Sauvage"]


def test_empty_query_returns_no_terms():
    assert catalog_search_terms("  ", Matcher(["anything"])) == []
