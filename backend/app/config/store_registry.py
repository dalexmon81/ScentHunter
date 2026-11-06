"""Central retailer identity and bounded-work configuration.

This module contains configuration only; importing it performs no I/O and
starts no workers. Keep the legacy values stable while services are extracted.
"""

STORES = [
    "bplatz", "deloox", "parfumcity", "parfumzentrum", "perfumemarket",
    "sabina", "orioudh", "easycosmetic", "notino",
]
STORE_LABELS = {
    "bplatz": "Bplatz",
    "deloox": "Deloox",
    "parfumcity": "ParfumCity",
    "parfumzentrum": "ParfumZentrum",
    "perfumemarket": "PerfumeMarket",
    "sabina": "Sabina",
    "orioudh": "Orioudh",
    "easycosmetic": "Easycosmetic",
    "notino": "Notino",
}

LIGHTWEIGHT_STORES = [
    "bplatz", "parfumcity", "parfumzentrum", "perfumemarket",
    "orioudh", "easycosmetic", "notino",
]
NETWORK_HEAVY_STORES = ["deloox"]
BROWSER_STORES = ["sabina"]

LIGHT_WORKERS = 2
NETWORK_WORKERS = 1
BROWSER_WORKERS = 1

STORE_TIMEOUT_SECONDS = 60.0
STORE_TIMEOUTS = {
    "bplatz": 60.0,
    "deloox": 75.0,
    "parfumcity": 60.0,
    "parfumzentrum": 60.0,
    "perfumemarket": 60.0,
    "sabina": 70.0,
    "orioudh": 60.0,
    "easycosmetic": 60.0,
    "notino": 45.0,
}
JOB_TIMEOUT_SECONDS = 30.0
CATALOG_SEARCH_BUDGET_SECONDS = 12.0
CATALOG_REFRESH_BUDGET_SECONDS = 0.25
CATALOG_REFRESH_PER_STORE = 8

# Keep category membership disjoint: each configured store has one execution
# profile, and every store has an explicit timeout.
def validate_store_registry():
    categories = (LIGHTWEIGHT_STORES, NETWORK_HEAVY_STORES, BROWSER_STORES)
    flattened = [store for group in categories for store in group]
    if len(flattened) != len(set(flattened)):
        raise ValueError("store_execution_categories_overlap")
    if set(flattened) != set(STORES):
        raise ValueError("store_execution_categories_mismatch")
    if set(STORE_TIMEOUTS) != set(STORES):
        raise ValueError("store_timeout_registry_mismatch")
    if any(timeout <= 0 for timeout in STORE_TIMEOUTS.values()):
        raise ValueError("store_timeout_must_be_positive")
    if min(LIGHT_WORKERS, NETWORK_WORKERS, BROWSER_WORKERS) < 1:
        raise ValueError("store_worker_limits_must_be_positive")
    return True


validate_store_registry()
