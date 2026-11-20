"""Root-level wrapper for the canonical catalog seed command."""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "backend" / "scripts" / "seed_catalog.py"), run_name="__main__")
