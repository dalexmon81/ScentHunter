
from fastapi import APIRouter
import importlib
import inspect
import hashlib
from pathlib import Path

router = APIRouter(prefix="/api/debug", tags=["debug-deloox-runtime"])

TARGETS = [
    "discover",
    "_candidate_contexts",
    "_row_from_card",
    "parse_product",
    "search",
    "search_stream",
    "product_url",
    "relevant",
    "clean",
    "norm",
    "tokens",
    "size_ml",
]

@router.get("/deloox-runtime-source")
def deloox_runtime_source():
    out = {
        "ok": False,
        "test": "DELOOX_RUNTIME_SOURCE_V5",
        "module": {},
        "functions": {},
        "notes": [
            "READ-ONLY",
            "No Deloox HTTP request",
            "No discover/search/parse_product execution",
            "Production scraper is not modified",
        ],
    }

    try:
        m = importlib.import_module("scrapers.deloox.scraper")
        path = Path(inspect.getfile(m)).resolve()
        data = path.read_bytes()

        out["module"] = {
            "file": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "line_count": len(data.decode("utf-8", errors="replace").splitlines()),
        }

        for name in TARGETS:
            fn = getattr(m, name, None)
            item = {
                "callable": callable(fn),
                "module": getattr(fn, "__module__", None),
                "signature": None,
                "source_start_line": None,
                "source": None,
            }
            if callable(fn):
                try:
                    item["signature"] = str(inspect.signature(fn))
                except Exception as exc:
                    item["signature_error"] = f"{type(exc).__name__}: {exc}"
                try:
                    src, start = inspect.getsourcelines(fn)
                    item["source_start_line"] = start
                    item["source"] = "".join(src)
                except Exception as exc:
                    item["source_error"] = f"{type(exc).__name__}: {exc}"
            out["functions"][name] = item

        out["ok"] = True
        return out

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
