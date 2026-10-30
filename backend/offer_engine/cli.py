"""Command-line runner for the isolated Offer Engine."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from backend.offer_engine.runtime import apply_migration, run_offer_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ScentHunter's isolated Offer Engine")
    parser.add_argument("--query", required=True, help="Retailer search query")
    parser.add_argument(
        "--apply-migration",
        action="store_true",
        help="Apply the additive sh_* PostgreSQL schema before running",
    )
    args = parser.parse_args()

    if args.apply_migration:
        apply_migration()

    result = run_offer_engine(args.query)
    print(json.dumps(asdict(result), ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
