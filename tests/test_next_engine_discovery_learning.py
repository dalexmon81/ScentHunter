from backend.scenthunter_next_engine.discovery_learning import learn_variants, learn_from_shadow_report


def _catalog():
    return {
        "products": [{
            "product_id": "SH-TEST-1",
            "brand_name": "Example",
            "canonical_name": "Blue Night",
            "concentration": "Eau de Parfum",
        }],
        "variants": [],
    }


def _offer(retailer, host, name="Blue Night Eau de Parfum", size=100, product_id="SH-TEST-1"):
    return {
        "product_id": product_id,
        "name": name,
        "brand": "Example",
        "size_ml": size,
        "retailer": retailer,
        "product_url": f"https://{host}/products/blue-night",
    }


def test_learns_variant_only_after_two_independent_retailer_domains():
    result = learn_variants(_catalog(), [
        _offer("Store A", "a.example"),
        _offer("Store B", "b.example"),
    ])
    assert result["report"]["variants_added"] == 1
    variant = result["catalog"]["variants"][0]
    assert variant["product_id"] == "SH-TEST-1"
    assert variant["size_ml"] == 100
    assert variant["variant_id"].startswith("VAR-")
    assert result["report"]["added_variants"][0]["independent_retailer_count"] == 2


def test_single_retailer_is_not_enough():
    result = learn_variants(_catalog(), [_offer("Store A", "a.example")])
    assert result["report"]["variants_added"] == 0
    assert result["report"]["rejected_observation_counts"]["insufficient_independent_retailers"] == 1


def test_does_not_learn_unknown_product_or_invent_product_identity():
    result = learn_variants(_catalog(), [
        _offer("Store A", "a.example", product_id="SH-NOT-FOUND"),
        _offer("Store B", "b.example", product_id="SH-NOT-FOUND"),
    ])
    assert result["report"]["variants_added"] == 0
    assert result["catalog"]["products"] == _catalog()["products"]


def test_rejects_concentration_conflict_and_special_packaging():
    result = learn_variants(_catalog(), [
        _offer("Store A", "a.example", name="Blue Night Eau de Toilette"),
        _offer("Store B", "b.example", name="Blue Night Eau de Parfum refill"),
    ])
    assert result["report"]["variants_added"] == 0
    assert result["report"]["rejected_observation_counts"]["concentration_unverified_or_conflict"] == 1
    assert result["report"]["rejected_observation_counts"]["special_packaging_requires_review"] == 1


def test_deterministic_id_and_existing_size_are_not_duplicated():
    observations = [_offer("Store A", "a.example"), _offer("Store B", "b.example")]
    first = learn_variants(_catalog(), observations)
    second = learn_variants(_catalog(), observations)
    assert first["catalog"]["variants"][0]["variant_id"] == second["catalog"]["variants"][0]["variant_id"]

    catalog = first["catalog"]
    again = learn_variants(catalog, observations)
    assert again["report"]["variants_added"] == 0


def test_shadow_report_ingestion_uses_unique_candidate_product_id():
    catalog = _catalog()
    report = {
        "queries": [{
            "retailers": [
                {"retailer": "Store A", "unresolved_examples": [{
                    "name": "Blue Night Eau de Parfum", "brand": "Example", "size_ml": 100,
                    "product_url": "https://a.example/p", "candidate_product_ids": ["SH-TEST-1"],
                }]},
                {"retailer": "Store B", "unresolved_examples": [{
                    "name": "Blue Night Eau de Parfum", "brand": "Example", "size_ml": 100,
                    "product_url": "https://b.example/p", "candidate_product_ids": ["SH-TEST-1"],
                }]},
            ],
        }],
    }
    result = learn_from_shadow_report(catalog, report)
    assert result["report"]["variants_added"] == 1


def test_proposes_unseen_perfume_only_after_two_retailers_agree():
    observations = [
        {
            "name": "New Moon Eau de Parfum",
            "brand": "Example",
            "size_ml": 50,
            "retailer": "Store A",
            "product_url": "https://a.example/new-moon",
            "candidate_product_ids": [],
        },
        {
            "name": "New Moon Eau de Parfum",
            "brand": "Example",
            "size_ml": 50,
            "retailer": "Store B",
            "product_url": "https://b.example/new-moon",
            "candidate_product_ids": [],
        },
    ]
    result = learn_variants(_catalog(), observations)
    assert result["report"]["products_added"] == 1
    assert result["report"]["variants_added"] == 1
    product = result["report"]["added_products"][0]
    variant = result["report"]["added_variants"][0]
    assert product["canonical_name"] == "New Moon"
    assert product["concentration"] == "eau de parfum"
    assert variant["product_id"] == product["product_id"]
    assert variant["size_ml"] == 50


def test_does_not_propose_new_perfume_from_one_retailer():
    result = learn_variants(_catalog(), [{
        "name": "New Moon Eau de Parfum",
        "brand": "Example",
        "size_ml": 50,
        "retailer": "Store A",
        "product_url": "https://a.example/new-moon",
        "candidate_product_ids": [],
    }])
    assert result["report"]["products_added"] == 0
    assert result["report"]["variants_added"] == 0


def test_rejects_title_url_concentration_conflict_before_learning():
    catalog = _catalog()
    observations = [
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store A",
            "product_url": "https://a.example/blue-night-parfum-100ml",
        },
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store B",
            "product_url": "https://b.example/blue-night-eau-de-parfum-100ml",
        },
    ]
    result = learn_variants(catalog, observations)
    assert result["report"]["variants_added"] == 0
    assert result["report"]["rejected_observation_counts"]["url_concentration_conflict"] == 1


def test_does_not_propose_unseen_product_when_url_concentration_conflicts():
    observations = [
        {
            "name": "New Moon Eau de Parfum",
            "brand": "Example",
            "size_ml": 50,
            "retailer": "Store A",
            "product_url": "https://a.example/new-moon-parfum",
            "candidate_product_ids": [],
        },
        {
            "name": "New Moon Eau de Parfum",
            "brand": "Example",
            "size_ml": 50,
            "retailer": "Store B",
            "product_url": "https://b.example/new-moon-eau-de-parfum",
            "candidate_product_ids": [],
        },
    ]
    result = learn_variants(_catalog(), observations)
    assert result["report"]["products_added"] == 0
    assert result["report"]["variants_added"] == 0
    assert result["report"]["rejected_observation_counts"]["url_concentration_conflict"] == 1



def test_rejects_url_concentration_conflict_and_refillable_packaging():
    concentration_conflict = learn_variants(_catalog(), [
        {
            **_offer("Store A", "a.example"),
            "product_url": "https://a.example/blue-night-eau-de-toilette-100ml",
        },
        _offer("Store B", "b.example"),
    ])
    assert concentration_conflict["report"]["variants_added"] == 0
    assert concentration_conflict["report"]["rejected_observation_counts"]["concentration_unverified_or_conflict"] == 1

    refillable = learn_variants(_catalog(), [
        {
            **_offer("Store A", "a.example"),
            "product_url": "https://a.example/blue-night-refillable-100ml",
        },
        _offer("Store B", "b.example"),
    ])
    assert refillable["report"]["variants_added"] == 0
    assert refillable["report"]["rejected_observation_counts"]["special_packaging_requires_review"] == 1


def test_proposes_distinct_perfume_when_single_candidate_is_only_a_broad_name_mismatch():
    observations = [
        {
            "name": "New Moon Eau de Parfum",
            "brand": "Example",
            "size_ml": 50,
            "retailer": "Store A",
            "product_url": "https://a.example/new-moon",
            "candidate_product_ids": ["SH-TEST-1"],
        },
        {
            "name": "New Moon Eau de Parfum",
            "brand": "Example",
            "size_ml": 50,
            "retailer": "Store B",
            "product_url": "https://b.example/new-moon",
            "candidate_product_ids": ["SH-TEST-1"],
        },
    ]
    result = learn_variants(_catalog(), observations)
    assert result["report"]["products_added"] == 1
    product = result["report"]["added_products"][0]
    assert product["canonical_name"] == "New Moon"
    assert product["product_id"] != "SH-TEST-1"
    assert result["report"]["variants_added"] == 1
    assert result["report"]["added_variants"][0]["product_id"] == product["product_id"]


def test_shadow_report_ingestion_includes_ambiguous_distinct_perfumes():
    catalog = _catalog()
    report = {
        "queries": [{
            "retailers": [
                {"retailer": "Store A", "ambiguous_examples": [{
                    "name": "New Moon Eau de Parfum", "brand": "Example", "size_ml": 50,
                    "product_url": "https://a.example/new-moon", "candidate_product_ids": ["SH-TEST-1"],
                }]},
                {"retailer": "Store B", "ambiguous_examples": [{
                    "name": "New Moon Eau de Parfum", "brand": "Example", "size_ml": 50,
                    "product_url": "https://b.example/new-moon", "candidate_product_ids": ["SH-TEST-1"],
                }]},
            ],
        }],
    }
    result = learn_from_shadow_report(catalog, report)
    assert result["report"]["products_added"] == 1
    assert result["report"]["added_products"][0]["canonical_name"] == "New Moon"
    assert result["report"]["variants_added"] == 1


def test_proposes_new_product_when_only_candidate_is_missing_family_placeholder():
    observations = [
        {
            "name": "Hawas Malibu Eau de Parfum",
            "brand": "Rasasi",
            "size_ml": 100,
            "retailer": "Store A",
            "product_url": "https://a.example/rasasi-hawas-malibu-eau-de-parfum-100ml",
            "candidate_product_ids": ["SH-FAMILY-not-in-catalog"],
        },
        {
            "name": "Hawas Malibu Eau de Parfum",
            "brand": "Rasasi",
            "size_ml": 100,
            "retailer": "Store B",
            "product_url": "https://b.example/rasasi-hawas-malibu-eau-de-parfum-100ml",
            "candidate_product_ids": ["SH-FAMILY-not-in-catalog"],
        },
    ]
    result = learn_variants(_catalog(), observations)
    assert result["report"]["products_added"] == 1
    product = result["report"]["added_products"][0]
    assert product["canonical_name"] == "Hawas Malibu"
    assert product["brand_name"] == "Rasasi"
    assert result["report"]["variants_added"] == 1
    assert result["report"]["added_variants"][0]["product_id"] == product["product_id"]

def test_rejects_variant_when_url_slug_identifies_a_distinct_flanker():
    catalog = {
        "products": [{
            "product_id": "SH-DIOR-S", "brand_name": "Dior",
            "canonical_name": "Sauvage", "concentration": "Eau de Parfum",
        }],
        "variants": [],
    }
    observations = [
        {
            "product_id": "SH-DIOR-S",
            "name": "Sauvage Eau de Parfum",
            "brand": "Dior",
            "size_ml": 60,
            "retailer": "Store A",
            "product_url": "https://a.example/dior-sauvage-eau-forte-eau-forte-60-ml",
        },
        {
            "product_id": "SH-DIOR-S",
            "name": "Sauvage Eau de Parfum",
            "brand": "Dior",
            "size_ml": 60,
            "retailer": "Store B",
            "product_url": "https://b.example/dior-sauvage-eau-forte-eau-forte-60-ml",
        },
    ]
    result = learn_variants(catalog, observations)
    assert result["report"]["variants_added"] == 0
    assert result["report"]["rejected_observation_counts"]["url_identity_conflict"] == 2


def test_url_identity_accepts_matching_product_slug_with_generic_packaging_words():
    catalog = {
        "products": [{
            "product_id": "SH-DIOR-S", "brand_name": "Dior",
            "canonical_name": "Sauvage", "concentration": "Eau de Parfum",
        }],
        "variants": [],
    }
    observations = [
        {
            "product_id": "SH-DIOR-S",
            "name": "Sauvage Eau de Parfum",
            "brand": "Dior",
            "size_ml": 60,
            "retailer": "Store A",
            "product_url": "https://a.example/dior-sauvage-edp-vapo-spray-60-ml",
        },
        {
            "product_id": "SH-DIOR-S",
            "name": "Sauvage Eau de Parfum",
            "brand": "Dior",
            "size_ml": 60,
            "retailer": "Store B",
            "product_url": "https://b.example/dior-sauvage-eau-de-parfum-spray-60-ml",
        },
    ]
    result = learn_variants(catalog, observations)
    assert result["report"]["variants_added"] == 1

def test_uses_explicit_url_concentration_when_retailer_title_omits_it():
    catalog = _catalog()
    observations = [
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store A",
            "product_url": "https://a.example/blue-night-eau-de-parfum-100ml",
        },
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store B",
            "product_url": "https://b.example/blue-night-edp-100ml",
        },
    ]
    result = learn_variants(catalog, observations)
    assert result["report"]["variants_added"] == 1
    assert result["report"]["added_variants"][0]["concentration"] == "eau de parfum"


def test_title_and_url_concentration_must_both_match_canonical_product():
    catalog = _catalog()
    observations = [
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store A",
            "product_url": "https://a.example/blue-night-eau-de-toilette-100ml",
        },
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store B",
            "product_url": "https://b.example/blue-night-eau-de-parfum-100ml",
        },
    ]
    result = learn_variants(catalog, observations)
    assert result["report"]["variants_added"] == 0
    assert result["report"]["rejected_observation_counts"]["concentration_unverified_or_conflict"] == 1
    assert result["report"]["rejected_observation_counts"]["url_concentration_conflict"] == 1

def test_rejects_deloox_spanish_route_on_belgian_market_during_learning():
    observations = [
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Deloox",
            "product_url": "https://www.deloox.be/producto/12345/blue-night-eau-de-parfum-100-ml.html",
        },
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store B",
            "product_url": "https://b.example/blue-night-eau-de-parfum-100ml",
        },
    ]
    result = learn_variants(_catalog(), observations)
    assert result["report"]["variants_added"] == 0
    assert result["report"]["rejected_observation_counts"]["storefront_locale_conflict"] == 1
    assert result["report"]["rejected_observation_counts"]["insufficient_independent_retailers"] == 1


def test_accepts_deloox_spanish_route_on_spanish_market():
    observations = [
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Deloox",
            "product_url": "https://www.deloox.es/producto/12345/blue-night-eau-de-parfum-100-ml.html",
        },
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store B",
            "product_url": "https://b.example/blue-night-eau-de-parfum-100ml",
        },
    ]
    result = learn_variants(_catalog(), observations)
    assert result["report"]["variants_added"] == 1

def test_nonstandard_catalog_concentration_label_does_not_block_explicit_variant_evidence():
    catalog = {
        "products": [{
            "product_id": "SH-HAWAS-ELIXIR",
            "brand_name": "Rasasi",
            "canonical_name": "Hawas Élixir",
            "concentration": "Elixir",
        }],
        "variants": [],
    }
    observations = [
        {
            "product_id": "SH-HAWAS-ELIXIR",
            "name": "Hawas Elixir",
            "brand": "Rasasi",
            "size_ml": 100,
            "retailer": "Store A",
            "product_url": "https://a.example/rasasi-hawas-elixir-100ml-edp",
        },
        {
            "product_id": "SH-HAWAS-ELIXIR",
            "name": "Hawas Elixir",
            "brand": "Rasasi",
            "size_ml": 100,
            "retailer": "Store B",
            "product_url": "https://b.example/rasasi-hawas-elixir-eau-de-parfum-100ml",
        },
    ]
    result = learn_variants(catalog, observations)
    assert result["report"]["variants_added"] == 1
    assert result["report"]["added_variants"][0]["size_ml"] == 100

def test_url_identity_allows_reordered_brand_and_gender_tokens():
    catalog = {
        "products": [{
            "product_id": "SH-VALENTINO-1",
            "brand_name": "Valentino",
            "canonical_name": "Born in Roma Donna",
            "concentration": "",
        }],
        "variants": [],
    }
    observations = [
        {
            "product_id": "SH-VALENTINO-1",
            "name": "Born in Roma Donna Eau de Parfum",
            "brand": "Valentino",
            "size_ml": 50,
            "retailer": "Store A",
            "product_url": "https://a.example/valentino-donna-born-in-roma-eau-de-parfum-50ml",
        },
        {
            "product_id": "SH-VALENTINO-1",
            "name": "Born in Roma Donna Eau de Parfum",
            "brand": "Valentino",
            "size_ml": 50,
            "retailer": "Store B",
            "product_url": "https://b.example/valentino-born-in-roma-donna-edp-vapo-50ml",
        },
    ]
    result = learn_variants(catalog, observations)
    assert result["report"]["variants_added"] == 1

def test_url_identity_ignores_retailer_product_ids_and_brand_suffixes():
    observations = [
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store A",
            "product_url": "https://a.example/12345-example-blue-night-eau-de-parfum-100ml-example",
        },
        {
            "product_id": "SH-TEST-1",
            "name": "Blue Night Eau de Parfum",
            "brand": "Example",
            "size_ml": 100,
            "retailer": "Store B",
            "product_url": "https://b.example/67890-blue-night-edp-100ml-by-example",
        },
    ]
    result = learn_variants(_catalog(), observations)
    assert result["report"]["variants_added"] == 1

