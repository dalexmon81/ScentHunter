import json

from app.services.product_matcher_bootstrap import load_product_matcher


class RecordingMatcher:
    def __init__(self, *, catalog, family_registry):
        self.catalog = catalog
        self.family_registry = family_registry


def test_loads_list_catalog_and_optional_family_registry(tmp_path):
    catalog_path = tmp_path / "product_catalog.json"
    family_path = tmp_path / "family_registry.json"
    catalog = [{"brand": "Dior", "name": "Sauvage"}]
    families = {"families": ["fresh"]}
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    family_path.write_text(json.dumps(families), encoding="utf-8")

    matcher = load_product_matcher(RecordingMatcher, catalog_path, family_path)

    assert matcher.catalog == catalog
    assert matcher.family_registry == families


def test_loads_dict_catalog_and_missing_family_registry(tmp_path):
    catalog_path = tmp_path / "product_catalog.json"
    family_path = tmp_path / "missing-family-registry.json"
    catalog = {"products": [{"brand": "Chanel"}]}
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    matcher = load_product_matcher(RecordingMatcher, catalog_path, family_path)

    assert matcher.catalog == catalog
    assert matcher.family_registry is None


def test_empty_or_unexpected_catalog_disables_matcher(tmp_path):
    catalog_path = tmp_path / "product_catalog.json"
    family_path = tmp_path / "family_registry.json"
    catalog_path.write_text(json.dumps({"products": []}), encoding="utf-8")
    assert load_product_matcher(RecordingMatcher, catalog_path, family_path) is None
    catalog_path.write_text(json.dumps("unexpected"), encoding="utf-8")
    assert load_product_matcher(RecordingMatcher, catalog_path, family_path) is None


def test_missing_catalog_fails_closed_without_raising(tmp_path):
    assert load_product_matcher(
        RecordingMatcher, tmp_path / "missing.json", tmp_path / "families.json"
    ) is None


def test_missing_matcher_class_returns_none(tmp_path):
    assert load_product_matcher(None, tmp_path / "catalog.json", tmp_path / "families.json") is None
