"""Update only the Liquid Brun pilot from a fresh Bplatz page observation."""
from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from scripts.check_bplatz_liquid_brun_live import fetch_live_offer  # noqa: E402


SEARCH_URL = "https://scenthunter.fly.dev/api/catalog/search"
STATUS_URL = "https://scenthunter.fly.dev/api/catalog/status"


def verify_public_api(report: dict) -> dict:
    response = requests.get(
        SEARCH_URL,
        params={"q": "French Avenue Liquid Brun EDP 100ml"},
        timeout=(5, 20),
    )
    response.raise_for_status()
    result = response.json()
    if result.get("status") != "completed" or result.get("count") != 1:
        raise RuntimeError("production catalog search did not return the Liquid Brun variant")
    product = result["results"][0]
    try:
        matches = [
            offer for offer in product.get("offers", [])
            if offer.get("store") == "Bplatz"
            and offer.get("availability") == "in_stock"
            and offer.get("currency") == "EUR"
            and offer.get("url") == report["url"]
            and Decimal(str(offer.get("price"))) == Decimal(str(report["price"]))
        ]
    except InvalidOperation as exc:
        raise RuntimeError("production catalog API returned an invalid offer price") from exc
    if len(matches) != 1:
        raise RuntimeError("production catalog API did not publish the exact verified live offer")

    response = requests.get(STATUS_URL, timeout=(5, 20))
    response.raise_for_status()
    status = response.json()
    if status.get("status") != "ready" or status.get("published_offers", 0) < 1:
        raise RuntimeError("production catalog status does not report a published offer")
    return {
        "search": result,
        "status": status,
    }


def main() -> int:
    if os.environ.get("CONFIRM_PRODUCTION_WRITE") != "true":
        raise SystemExit("STOP: set CONFIRM_PRODUCTION_WRITE=true to authorize the one-off pilot write")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("STOP: the live pilot writer may run only from the deployed main branch")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not run_id.isdecimal():
        raise SystemExit("STOP: missing or invalid GitHub Actions run id")

    try:
        report = fetch_live_offer()
        payload = base64.b64encode(
            json.dumps(report, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        remote_command = (
            "cd /app/backend && /app/.venv/bin/python "
            "scripts/persist_bplatz_phase2_live_offer.py "
            f"--run-id {shlex.quote(run_id)} "
            f"--payload-base64 {shlex.quote(payload)}"
        )
        print("BPLATZ_LIQUID_BRUN_LIVE_CHECK=" + json.dumps(report, ensure_ascii=False), flush=True)
        subprocess.run(
            [
                "flyctl", "ssh", "console", "--app", "scenthunter",
                "--select=false", "-C", shlex.join(["/bin/sh", "-lc", remote_command]),
            ],
            check=True,
            timeout=300,
        )
        verification = verify_public_api(report)
    except (OSError, requests.RequestException, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({
            "status": "failed",
            "reason": str(exc),
            "database_written": "unknown; inspect the verified backup and Fly logs if the remote write started",
        }, ensure_ascii=False), file=sys.stderr)
        return 1

    print("PRODUCTION_CATALOG_LIQUID_BRUN=" + json.dumps(verification, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
