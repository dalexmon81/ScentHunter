"""Review-only proposal for known invalid production Deloox URL rows.

The report is derived from the latest successful Fly SQLite audit output, not
from a local CI database. It does not execute SQL or mutate production. Rows
are proposals only and require an explicitly authorized maintenance operation.
"""
from __future__ import annotations

import json
from pathlib import Path

PRODUCTION_AUDIT_TIMESTAMP_UTC = "2026-10-24T03:32:51Z"
PRODUCTION_DATABASE = "/data/store_catalog.sqlite3"
PRODUCTION_AUDIT_RUN = "https://github.com/dalexmon81/ScentHunter/actions/runs/40058640195"

INVALID_URLS = (
    {
        "url": "https://www.deloox.com/search.html",
        "table": ["store_urls", "store_products"],
        "classification": "search_route_not_product",
        "action_proposal": "review_deactivate_store_urls_and_quarantine_offer_row",
    },
    {
        "url": "https://www.deloox.com/en/search.html",
        "table": ["store_urls"],
        "classification": "search_route_not_product",
        "action_proposal": "review_deactivate_store_urls",
    },
    {
        "url": "https://www.deloox.be/chercher.html",
        "table": ["store_urls", "store_products"],
        "classification": "search_route_not_product",
        "action_proposal": "review_deactivate_store_urls_and_quarantine_offer_row",
    },
    {
        "url": "https://www.deloox.lu/chercher.html",
        "table": ["store_urls", "store_products"],
        "classification": "search_route_not_product",
        "action_proposal": "review_deactivate_store_urls_and_quarantine_offer_row",
    },
    {
        "url": "https://www.deloox.lu/fr/chercher.html",
        "table": ["store_urls"],
        "classification": "search_route_not_product",
        "action_proposal": "review_deactivate_store_urls",
    },
    {
        "url": "https://www.deloox.nl/zoeken.html",
        "table": ["store_urls", "store_products"],
        "classification": "search_route_not_product",
        "action_proposal": "review_deactivate_store_urls_and_quarantine_offer_row",
    },
    {
        "url": "https://www.deloox.es/buscar.html",
        "table": ["store_urls", "store_products"],
        "classification": "search_route_not_product",
        "action_proposal": "review_deactivate_store_urls_and_quarantine_offer_row",
    },
)


def build_proposal() -> dict:
    """Create a deterministic, zero-side-effect proposal from fixed audit evidence."""
    return {
        "status": "REVIEW_REQUIRED",
        "proposal_type": "production_data_cleanup_review",
        "source": {
            "kind": "successful_read_only_fly_sqlite_audit",
            "workflow_run": PRODUCTION_AUDIT_RUN,
            "database": PRODUCTION_DATABASE,
            "generated_at_utc": PRODUCTION_AUDIT_TIMESTAMP_UTC,
        },
        "read_only": True,
        "production_database_mutated": False,
        "execution_performed": False,
        "counts_from_source_audit": {
            "active_deloox_urls_examined": 30768,
            "invalid_active_urls_found": 7,
            "store_products_deloox_rows": 32209,
            "parser_not_found_rows": 4548,
            "hydration_queue": {
                "DEAD": 5035,
                "DONE": 25792,
                "ERROR": 6,
                "PENDING": 563,
            },
            "deloox_store_product_variants": 0,
        },
        "proposed_url_actions": list(INVALID_URLS),
        "classification_policy": {
            "search_or_homepage_url": (
                "Not a product. Keep the URL, fetch status and evidence in this review report; "
                "do not treat it as an offer or delete the row automatically."
            ),
            "product_url_with_parser_error": (
                "Keep distinct from a navigation URL. Re-test with a retained response fixture "
                "or a verified runtime probe before any retry/quarantine decision."
            ),
            "canonical_identity_duplicate": (
                "Review by normalized brand, model and concentration plus variant-level evidence. "
                "Never merge by name alone."
            ),
            "unreachable_product": (
                "Do not assume invalid product identity from one HTTP failure. Classify as "
                "temporarily unreachable only after repeated time-bounded checks."
            ),
        },
        "known_identity_review": {
            "brand": "Giorgio Armani",
            "normalized_identity": "armani|acqua di gio profondo|eau de parfum",
            "candidate_product_ids": ["SH-0043", "SH-AUTO-0019"],
            "SH-0043": {
                "canonical_name": "Acqua di Gio Profondo",
                "concentration": "Eau de Parfum",
                "variant_sizes_ml": [75, 125],
                "coverage": {
                    "deloox": {"state": "PROCESSING", "found_urls": 0},
                    "easycosmetic": {"state": "FOUND", "found_urls": 5},
                },
            },
            "SH-AUTO-0019": {
                "canonical_name": "Acqua di Giò Profondo",
                "concentration": "Eau de Parfum",
                "variant_sizes_ml": [50, 100, 200],
                "coverage": {
                    "deloox": {
                        "state": "RETRY",
                        "found_urls": 0,
                        "last_error": "coverage_timeout_after_30s",
                    },
                    "easycosmetic": {"state": "NOT_FOUND", "found_urls": 0},
                },
            },
            "recommended_disposition": (
                "High-confidence duplicate canonical identity candidate, but defer merge. "
                "First verify all five sizes and offers using source URLs/GTIN/MPN; then create "
                "a reviewed mapping proposal that keeps EDT and EDP separate."
            ),
            "production_change_performed": False,
        },
        "approval_gate": {
            "production_deactivation_or_quarantine_authorized": False,
            "canonical_merge_authorized": False,
            "migration_authorized": False,
            "required_next_evidence": [
                "Fresh read-only SQLite report immediately before any maintenance",
                "A row-level SELECT snapshot including primary keys and foreign-key references",
                "A reversible transaction plan with row counts and rollback SQL",
                "Regression test proving only known search routes are excluded",
                "Explicit human approval before executing any production change",
            ],
        },
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    output_path = root / "production-cleanup-proposal.json"
    report = build_proposal()
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "read_only": report["read_only"],
        "production_database_mutated": report["production_database_mutated"],
        "invalid_url_proposals": len(report["proposed_url_actions"]),
        "canonical_merge_authorized": report["approval_gate"]["canonical_merge_authorized"],
        "report_file": output_path.name,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
