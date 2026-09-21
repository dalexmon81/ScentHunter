"""
ScentHunter runtime bootstrap.

INTENTIONALLY EMPTY.

All eight production scrapers now expose their own native `search_stream`
contract. Scraper-specific adapters, product-specific fallbacks, hidden
discovery paths and runtime monkey-patching have been removed.

This file remains only because Python may auto-import `sitecustomize` when
PYTHONPATH points at /app/backend. Keeping the module as a no-op preserves
startup compatibility without creating a second scraper architecture.
"""

# No monkey-patching.
# No scraper imports.
# No product-specific rules.
# No fallback matching.
# No hidden catalog.
