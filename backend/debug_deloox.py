from __future__ import annotations

import hashlib
import inspect
import json
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])


def _fingerprint(module):
    path = getattr(module, "__file__", None)
    out = {
        "file": path,
        "origin": getattr(getattr(module, "__spec__", None), "origin", None),
        "sha256": None,
        "lines": None,
        "size_bytes": None,
    }
    try:
        if path:
            raw = open(path, "rb").read()
            out["sha256"] = hashlib.sha256(raw).hexdigest()
            out["lines"] = raw.count(b"\n") + 1
            out["size_bytes"] = len(raw)
    except Exception as e:
        out["file_read_error"] = f"{type(e).__name__}: {e}"
    return out


def _function_info(module, name):
    fn = getattr(module, name, None)
    if not callable(fn):
        return {"exists": False}

    out = {
        "exists": True,
        "object": repr(fn),
    }

    try:
        out["signature"] = str(inspect.signature(fn))
    except Exception as e:
        out["signature_error"] = f"{type(e).__name__}: {e}"

    try:
        src = inspect.getsource(fn)
        out["source_head"] = src[:12000]
        out["source_chars"] = len(src)
    except Exception as e:
        out["source_error"] = f"{type(e).__name__}: {e}"

    return out


@router.get("/deloox-runtime-fingerprint-v4")
def deloox_runtime_fingerprint_v4(
    q: str = Query("Born in Roma", min_length=1),
):
    try:
        import importlib

        module = importlib.import_module("scrapers.deloox.scraper")

        return {
            "ok": True,
            "diagnostic": "DELOOX_RUNTIME_FINGERPRINT_V4",
            "read_only": True,
            "query": q,
            "module": _fingerprint(module),
            "functions": {
                name: _function_info(module, name)
                for name in (
                    "discover",
                    "_discover",
                    "_candidate_contexts",
                    "_candidate_product_urls",
                    "_row_from_card",
                    "product_url",
                    "relevant",
                    "matches",
                    "search",
                    "search_stream",
                )
            },
        }

    except Exception as e:
        return {
            "ok": False,
            "diagnostic": "DELOOX_RUNTIME_FINGERPRINT_V4",
            "error": f"{type(e).__name__}: {e}",
        }
