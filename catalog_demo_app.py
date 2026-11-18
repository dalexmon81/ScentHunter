"""Root-level ASGI shim for Render's repository-root service."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND))

from catalog_demo_app import app  # noqa: E402,F401
