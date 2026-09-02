"""
ScentHunter API entrypoint.

IMPORTANT:
The current working backend/main.py must first be renamed to
backend/main_legacy.py without changing its contents.

This thin entrypoint then loads the legacy application and replaces only the
live search orchestration with the robust central SearchEngine.
"""

import main_legacy as _legacy
from main_legacy import *
from search_engine import SearchEngine


# One central search engine, reusing the existing:
# - ProductMatcher
# - Family Registry
# - product catalog
# - eight store adapters
# - central validation/finalization functions
_engine = SearchEngine(_legacy)


# The FastAPI route functions live inside main_legacy.py and therefore resolve
# their globals in the legacy module's namespace.  Patch that namespace
# explicitly; assigning only local wrapper globals would NOT change the routes.
_legacy.search_perfume = _engine.search
_legacy._run_search_job = _engine.run_job


# Keep the exact FastAPI application object and every existing route.
app = _legacy.app
