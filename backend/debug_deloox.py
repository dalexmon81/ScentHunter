from fastapi import APIRouter
import importlib
import inspect
import hashlib

router = APIRouter(prefix="/api/debug", tags=["debug-deloox-matcher"])

ROWS = [
    {
        "url": "https://www.deloox.be/produit/1400167/valentino-born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html",
        "brand": "Valentino",
        "name": "Valentino Born in Roma Ivory Uomo Eau de Toilette Limited edition 100 ml",
        "price": "100,49 €",
        "price_num": 100.49,
        "size_ml": 100,
        "store": "Deloox",
    },
    {
        "url": "https://www.deloox.be/produit/1400164/valentino-donna-born-in-roma-ivory-eau-de-parfum-limited-edition-100-ml.html",
        "brand": "Valentino",
        "name": "Valentino Donna Born in Roma Ivory Eau de Parfum Limited edition 100 ml",
        "price": "121,59 €",
        "price_num": 121.59,
        "size_ml": 100,
        "store": "Deloox",
    },
]

def _safe(fn, *args):
    try:
        return {"ok": True, "value": fn(*args)}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}

@router.get("/deloox-ivory-matcher-proof")
def deloox_ivory_matcher_proof():
    out = {
        "ok": True,
        "test": "TEST_13_DELOOX_IVORY_MATCHER_RUNTIME_PROOF",
        "query": "Born in Roma",
    }
    try:
        main = importlib.import_module("main")
        pm = importlib.import_module("product_matcher")
        matcher = getattr(main, "PRODUCT_MATCHER", None)

        pm_file = getattr(pm, "__file__", "")
        pm_src = inspect.getsource(pm)
        out["runtime"] = {
            "main_file": getattr(main, "__file__", ""),
            "product_matcher_file": pm_file,
            "product_matcher_sha256": hashlib.sha256(pm_src.encode("utf-8")).hexdigest(),
            "matcher_type": type(matcher).__name__ if matcher is not None else None,
            "matcher_signature": str(inspect.signature(matcher.match)) if matcher is not None else None,
            "has_family_registry": bool(getattr(matcher, "family_registry", None)) if matcher is not None else False,
            "family_count": len(getattr(matcher, "family_registry", []) or []) if matcher is not None else 0,
        }

        cleaner = getattr(matcher, "_remove_brand", None) if matcher is not None else None
        family_query = getattr(matcher, "_family_for_query", None) if matcher is not None else None
        family_variant = getattr(matcher, "_family_variant_for_offer", None) if matcher is not None else None
        clean_text = getattr(pm, "catalog_clean_text", None)

        out["helpers"] = {
            "catalog_clean_text_source": inspect.getsource(clean_text) if callable(clean_text) else None,
            "catalog_clean_text_ivory_uomo": _safe(clean_text, ROWS[0]["name"]) if callable(clean_text) else None,
            "catalog_clean_text_ivory_donna": _safe(clean_text, ROWS[1]["name"]) if callable(clean_text) else None,
            "family_for_query": _safe(family_query, "Born in Roma") if callable(family_query) else None,
        }

        exact = []
        for row in ROWS:
            item = dict(row)
            trace = {"url": row["url"], "name": row["name"]}
            if callable(family_query):
                family = _safe(family_query, "Born in Roma")
                trace["family"] = family
                if family.get("ok") and callable(family_variant):
                    trace["family_variant"] = _safe(family_variant, item, family["value"])
            if matcher is not None:
                trace["match"] = _safe(matcher.match, item, "Born in Roma")
            exact.append(trace)

        out["ivory_results"] = exact

        apply_identity = getattr(main, "_apply_product_identity", None)
        if callable(apply_identity):
            out["apply_product_identity"] = [
                {
                    "url": row["url"],
                    "result": _safe(apply_identity, dict(row), "Born in Roma"),
                }
                for row in ROWS
            ]

        return out
    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        return out
