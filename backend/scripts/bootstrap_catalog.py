"""Bootstrap the isolated catalog pilot before API and worker startup.

This is safe to run on every single-machine pilot restart:
- Alembic upgrades the mounted canonical catalog schema.
- Canonical product identities are imported idempotently.
- Retailer activation remains an explicit operator action; this script does not
  create/activate stores and does not start a feed import itself.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def bootstrap_commands(python: str | None = None) -> list[list[str]]:
    executable = python or sys.executable
    return [
        [executable, "-m", "alembic", "upgrade", "head"],
        [executable, str(BACKEND / "scripts" / "seed_catalog.py"), "--apply"],
    ]


def main() -> int:
    for index, command in enumerate(bootstrap_commands(), start=1):
        step = "migrations" if index == 1 else "canonical_seed"
        print(f"CATALOG_BOOTSTRAP step={step} status=starting", flush=True)
        subprocess.run(command, cwd=BACKEND, check=True)
        print(f"CATALOG_BOOTSTRAP step={step} status=complete", flush=True)

    print("CATALOG_BOOTSTRAP status=ready", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
