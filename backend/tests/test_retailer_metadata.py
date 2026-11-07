from app.services.retailer_metadata import clean_retailer_brand_metadata


def test_clears_retailer_labels_recursively_without_touching_product_brands():
    source = {
        "brand": "Sabina",
        "manufacturer": "Dior",
        "nested": [
            {"source_brand": "SAB-INA", "brand": "Chanel"},
            ({"manufacturer": " sabina "}, "unchanged"),
        ],
    }

    cleaned = clean_retailer_brand_metadata(source, "sabina")

    assert cleaned == {
        "brand": "",
        "manufacturer": "Dior",
        "nested": [
            {"source_brand": "", "brand": "Chanel"},
            ({"manufacturer": ""}, "unchanged"),
        ],
    }
    assert source["brand"] == "Sabina"
    assert source["nested"][0]["source_brand"] == "SAB-INA"


def test_non_container_values_and_unrelated_labels_are_preserved():
    assert clean_retailer_brand_metadata("Dior", "sabina") == "Dior"
    assert clean_retailer_brand_metadata(
        {"brand": "Deloox", "value": 42}, "sabina"
    ) == {"brand": "Deloox", "value": 42}


def test_supports_none_and_empty_container_values():
    assert clean_retailer_brand_metadata(None, "sabina") is None
    assert clean_retailer_brand_metadata([], "sabina") == []
    assert clean_retailer_brand_metadata((), "sabina") == ()
