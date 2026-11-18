"""Root-level ASGI shim for Render's repository-root service."""
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND))

from backend.catalog_demo_app import app  # noqa: E402,F401
