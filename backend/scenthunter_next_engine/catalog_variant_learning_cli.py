"""Generate a reviewable catalog proposal from production shadow evidence.

The source catalog is never overwritten. The output is a separate proposal plus
an evidence report suitable for code review and rollback.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .discovery_learning import learn_from_shadow_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="backend/product_catalog.json")
    parser.add_argument("--report", required=True)
    parser.add_argument("--output-catalog", default="next-engine-catalog-proposal.json")
    parser.add_argument("--output-report", default="next-engine-catalog-learning-report.json")
    args = parser.parse_args()

    catalog_path = Path(args.catalog)
    report_path = Path(args.report)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    shadow = json.loads(report_path.read_text(encoding="utf-8"))
    result = learn_from_shadow_report(catalog, shadow)

    Path(args.output_catalog).write_text(
        json.dumps(result["catalog"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    audit = dict(result["report"])
    audit.update({
        "source_catalog": str(catalog_path),
        "source_shadow_report": str(report_path),
        "proposal_catalog": args.output_catalog,
        "source_catalog_overwritten": False,
    })
    Path(args.output_report).write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "proposal_generated",
        "variants_added": audit["variants_added"],
        "source_catalog_overwritten": False,
        "proposal_catalog": args.output_catalog,
        "proposal_report": args.output_report,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
