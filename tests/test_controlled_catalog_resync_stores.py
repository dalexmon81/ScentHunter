from backend import main


def test_controlled_catalog_resync_includes_parfumzentrum_gap():
    assert "parfumzentrum" in main._CATALOG_RESYNC_STORES
    assert "sabina" in main._CATALOG_RESYNC_STORES
    assert "deloox" in main._CATALOG_RESYNC_STORES
