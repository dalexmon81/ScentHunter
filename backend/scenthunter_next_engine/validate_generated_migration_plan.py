"""Validate the generated migration review plan without modifying any source data."""
from __future__ import annotations

import json
from pathlib import Path

from .validate_migration_plan import validate_plan_counts


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    report_path = repository_root / "catalog-migration-plan.json"

    try:
        with report_path.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "status": "error",
            "report_file": "catalog-migration-plan.json",
            "error": str(exc),
            "migration_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2

    result = validate_plan_counts(report)
    output = {
        **result,
        "report_file": "catalog-migration-plan.json",
        "migration_gate_must_remain_closed": True,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
