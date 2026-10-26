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
