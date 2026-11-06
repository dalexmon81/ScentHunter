from app.services.offer_filtering import is_non_fragrance_offer


def test_rejects_non_mapping_input():
    assert is_non_fragrance_offer(None)
    assert is_non_fragrance_offer("perfume")


def test_rejects_explicit_non_fragrance_flag():
    assert is_non_fragrance_offer({"is_fragrance": False})


def test_rejects_gift_sets_and_samples_from_title():
    assert is_non_fragrance_offer({"name": "Dior Sauvage gift set"})
    assert is_non_fragrance_offer({"title": "Discovery set samples"})


def test_rejects_non_fragrance_category():
    assert is_non_fragrance_offer({"name": "Face cleanser", "category": "skincare"})


def test_rejects_narrow_non_fragrance_url_slug():
    assert is_non_fragrance_offer({"name": "Daily product", "url": "https://shop.example/face-wash"})


def test_keeps_regular_perfume_offer():
    assert not is_non_fragrance_offer({
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "category": "Fragrance",
        "url": "https://shop.example/dior-sauvage-edp-100",
    })


def test_does_not_reject_valid_perfume_for_broad_url_word():
    assert not is_non_fragrance_offer({
        "name": "Home fragrance perfume",
        "url": "https://shop.example/perfume/home-collection",
    })
