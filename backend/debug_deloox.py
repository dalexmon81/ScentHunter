# ScentHunter - Deloox runtime fingerprint V4
# READ-ONLY DIAGNOSTIC.
# Does NOT call Deloox, discover(), search(), ProductMatcher, or modify production code.

from fastapi import APIRouter
import hashlib
import inspect
import importlib
from pathlib import Path

router = APIRouter(prefix="/api/debug", tags=["debug-deloox-runtime"])


def _source_info(obj):
    info = {
        "callable": callable(obj),
        "module": getattr(obj, "__module__", None),
        "name": getattr(obj, "__name__", None),
        "signature": None,
        "source_file": None,
        "source_start_line": None,
    }
    if callable(obj):
        try:
            info["signature"] = str(inspect.signature(obj))
        except Exception as exc:
            info["signature_error"] = f"{type(exc).__name__}: {exc}"
        try:
            source_file = inspect.getsourcefile(obj)
            info["source_file"] = source_file
            if source_file:
                try:
                    _, start = inspect.getsourcelines(obj)
                    info["source_start_line"] = start
                except Exception:
                    pass
        except Exception as exc:
            info["source_error"] = f"{type(exc).__name__}: {exc}"
    return info


@router.get("/deloox-runtime-fingerprint")
def deloox_runtime_fingerprint():
    result = {
        "ok": False,
        "test": "DELOOX_RUNTIME_FINGERPRINT_V4",
        "module": {},
        "functions": {},
        "notes": [
            "READ-ONLY diagnostic",
            "No Deloox HTTP request is performed",
            "No discover/search/parse_product call is performed",
            "No production scraper is modified",
        ],
    }

    try:
        module = importlib.import_module("scrapers.deloox.scraper")

        module_file = getattr(module, "__file__", None)
        module_origin = getattr(getattr(module, "__spec__", None), "origin", None)

        module_info = {
            "file": module_file,
            "origin": module_origin,
            "module_name": getattr(module, "__name__", None),
        }

        if module_file:
            try:
                path = Path(module_file).resolve()
                data = path.read_bytes()
                module_info.update({
                    "resolved_file": str(path),
                    "exists": path.exists(),
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "line_count": data.count(b"\n") + (1 if data else 0),
                })
            except Exception as exc:
                module_info["file_read_error"] = f"{type(exc).__name__}: {exc}"

        result["module"] = module_info

        names = [
            "discover",
            "_discover",
            "_candidate_contexts",
            "_candidate_product_urls",
            "product_url",
            "relevant",
            "matches",
            "_row_from_card",
            "parse_product",
            "search",
            "search_stream",
        ]

        result["functions"] = {
            name: _source_info(getattr(module, name, None))
            for name in names
        }

        result["ok"] = True
        return result

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
