"""Command-line runner for the isolated Offer Engine."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .runtime import apply_migration, run_offer_engine, seed_canonical_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ScentHunter's isolated Offer Engine")
    parser.add_argument("--query", help="Retailer search query")
    parser.add_argument(
        "--seed-catalog", action="store_true",
        help="Safely stage explicit canonical products/variants into the isolated database",
    )
    parser.add_argument(
        "--apply-migration",
        action="store_true",
        help="Apply the additive sh_* PostgreSQL schema before running",
    )
    args = parser.parse_args()

    if not args.query and not args.seed_catalog:
        parser.error("provide --query and/or --seed-catalog")
    if args.seed_catalog and not args.apply_migration:
        parser.error("--seed-catalog requires --apply-migration or an already migrated isolated database")
    if args.apply_migration:
        apply_migration()
    if args.seed_catalog:
        seeded = seed_canonical_catalog()
        print(json.dumps({"catalog_staging": seeded}, ensure_ascii=False, default=str, indent=2))
    if args.query:
        result = run_offer_engine(args.query)
        print(json.dumps(asdict(result), ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
