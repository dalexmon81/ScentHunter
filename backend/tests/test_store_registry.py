from app.config import store_registry


def test_every_store_has_one_execution_profile_and_timeout():
    assert store_registry.validate_store_registry() is True
    categories = (
        store_registry.LIGHTWEIGHT_STORES
        + store_registry.NETWORK_HEAVY_STORES
        + store_registry.BROWSER_STORES
    )
    assert sorted(categories) == sorted(store_registry.STORES)
    assert set(store_registry.STORE_TIMEOUTS) == set(store_registry.STORES)


def test_store_labels_cover_all_configured_stores():
    assert set(store_registry.STORE_LABELS) == set(store_registry.STORES)


def test_execution_limits_are_bounded_and_positive():
    assert store_registry.LIGHT_WORKERS == 2
    assert store_registry.NETWORK_WORKERS == 1
    assert store_registry.BROWSER_WORKERS == 1
    assert all(timeout > 0 for timeout in store_registry.STORE_TIMEOUTS.values())
