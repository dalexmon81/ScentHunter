from backend.scripts.build_notino_match_candidates import build_catalog_index


def test_candidate_index_includes_legacy_singular_variant_gtin():
    catalog = {
        "products": [{
            "product_id": "P-1",
            "brand_name": "Example Brand",
            "canonical_name": "Example Fragrance",
        }],
        "variants": [{
            "variant_id": "V-1",
            "product_id": "P-1",
            "size_ml": 100,
            "concentration": "EDP",
            "gtin": "4006381333931",
        }],
    }

    indexed = build_catalog_index(catalog)

    assert len(indexed) == 1
    assert indexed[0]["gtins"] == ["4006381333931"]


def test_candidate_index_prefers_gtins_array_when_present():
    catalog = {
        "products": [{
            "product_id": "P-1",
            "brand_name": "Example Brand",
            "canonical_name": "Example Fragrance",
        }],
        "variants": [{
            "variant_id": "V-1",
            "product_id": "P-1",
            "size_ml": 100,
            "concentration": "EDP",
            "gtin": "4006381333931",
            "gtins": ["4006381333931", "5901234123457"],
        }],
    }

    indexed = build_catalog_index(catalog)

    assert indexed[0]["gtins"] == ["4006381333931", "5901234123457"]
