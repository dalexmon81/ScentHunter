"""Product-form classification stays separate from concentration and size."""
import json

import pytest

from backend.scenthunter_next_engine.catalog_preflight import audit_catalog_data
from backend.scenthunter_next_engine.catalog_repository import CatalogFormatError, CatalogRepository
from backend.scenthunter_next_engine.models import CanonicalProduct, ProductForm


def test_product_form_defaults_to_unknown_for_legacy_catalog_records():
    product = CanonicalProduct(product_id="p1", brand="Brand", name="Scent")
    assert product.product_form is ProductForm.UNKNOWN


def test_product_form_is_validated_and_does_not_replace_concentration(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "products": [{
            "product_id": "p1", "brand_name": "Brand", "canonical_name": "Scent",
            "concentration": "Eau de Parfum", "product_form": "perfume_oil",
        }],
        "variants": [{"variant_id": "v1", "product_id": "p1", "size_ml": 30}],
    }), encoding="utf-8")
    product = CatalogRepository.from_file(path).all_products()[0]
    assert product.product_form is ProductForm.PERFUME_OIL
    assert product.concentration == "Eau de Parfum"
    assert product.variants[0].size_ml == 30


def test_repository_rejects_unknown_product_form_values(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "products": [{
            "product_id": "p1", "brand_name": "Brand", "canonical_name": "Scent",
            "product_form": "guess_from_name",
        }],
        "variants": [],
    }), encoding="utf-8")
    with pytest.raises(CatalogFormatError, match="Unsupported product_form"):
        CatalogRepository.from_file(path)


def test_preflight_reports_legacy_unknown_and_invalid_product_forms():
    result = audit_catalog_data({
        "products": [
            {"product_id": "p1"},
            {"product_id": "p2", "product_form": "deodorant"},
            {"product_id": "p3", "product_form": "invented"},
        ],
        "variants": [],
    })
    assert result["product_form_counts"] == {
        "deodorant": 1, "unknown": 1, "invented": 1,
    }
    assert result["invalid_product_form_count"] == 1
    assert {"code": "products_invalid_product_form", "count": 1} in result["findings"]
