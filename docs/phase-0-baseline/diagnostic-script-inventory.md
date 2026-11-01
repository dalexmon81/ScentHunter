# Diagnostic and debug script inventory

The following 24 standalone scripts were found at the top level of `backend/`. They are being relocated without editing their contents so historical investigations remain reproducible and the production package root is cleaner.

## Diagnostics
- `backend/diagnose_deloox_frontier_path.py` → `tools/diagnostics/diagnose_deloox_frontier_path.py`
- `backend/diagnose_deloox_scraper.py` → `tools/diagnostics/diagnose_deloox_scraper.py`
- `backend/diagnose_easycosmetic_de_variants_readonly.py` → `tools/diagnostics/diagnose_easycosmetic_de_variants_readonly.py`
- `backend/diagnose_easycosmetic_refresh_handoff.py` → `tools/diagnostics/diagnose_easycosmetic_refresh_handoff.py`
- `backend/diagnose_easycosmetic_trace.py` → `tools/diagnostics/diagnose_easycosmetic_trace.py`
- `backend/diagnose_easycosmetic_variant_discovery.py` → `tools/diagnostics/diagnose_easycosmetic_variant_discovery.py`
- `backend/diagnose_easycosmetic_variants_readonly.py` → `tools/diagnostics/diagnose_easycosmetic_variants_readonly.py`
- `backend/diagnose_parfumzentrum_hawas_gap.py` → `tools/diagnostics/diagnose_parfumzentrum_hawas_gap.py`
- `backend/diagnose_sabina_catalog_variants_read_only.py` → `tools/diagnostics/diagnose_sabina_catalog_variants_read_only.py`
- `backend/diagnose_sabina_legacy_crawl.py` → `tools/diagnostics/diagnose_sabina_legacy_crawl.py`
- `backend/diagnose_sabina_legacy_sparam.py` → `tools/diagnostics/diagnose_sabina_legacy_sparam.py`
- `backend/diagnose_sabina_persistence_path_read_only.py` → `tools/diagnostics/diagnose_sabina_persistence_path_read_only.py`
- `backend/diagnose_sabina_real_seeds.py` → `tools/diagnostics/diagnose_sabina_real_seeds.py`
- `backend/diagnose_sabina_refresh_parser_read_only.py` → `tools/diagnostics/diagnose_sabina_refresh_parser_read_only.py`
- `backend/diagnose_sabina_search.py` → `tools/diagnostics/diagnose_sabina_search.py`
- `backend/diagnose_sabina_search_stream.py` → `tools/diagnostics/diagnose_sabina_search_stream.py`
- `backend/diagnose_sabina_variant_callpath_read_only.py` → `tools/diagnostics/diagnose_sabina_variant_callpath_read_only.py`
- `backend/diagnose_sabina_variant_queue_read_only.py` → `tools/diagnostics/diagnose_sabina_variant_queue_read_only.py`
- `backend/diagnose_sabina_variant_runtime_read_only.py` → `tools/diagnostics/diagnose_sabina_variant_runtime_read_only.py`
- `backend/diagnose_sabina_variants_readonly.py` → `tools/diagnostics/diagnose_sabina_variants_readonly.py`
- `backend/diagnose_two_scrapers.py` → `tools/diagnostics/diagnose_two_scrapers.py`

## Debug / recovery
- `backend/debug_deloox.py` → `tools/debug/debug_deloox.py`
- `backend/debug_sabina.py` → `tools/debug/debug_sabina.py`
- `backend/recover_stale_parser_errors.py` → `tools/diagnostics/recover_stale_parser_errors.py`

These are moved as repository files only. The code is not invoked by production. Before deleting any helper, inspect whether it contains unique test fixtures or operational knowledge and preserve that knowledge in tests/docs.
