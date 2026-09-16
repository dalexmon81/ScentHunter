import importlib
import inspect
import hashlib
from fastapi import APIRouter

router = APIRouter()

@router.get("/deloox-ivory-key-proof")
def deloox_ivory_key_proof(q: str = "Born in Roma"):
    out = {
        "ok": True,
        "test": "TEST_14_DELOOX_IVORY_VARIANT_KEY_PROOF",
        "query": q,
    }
    try:
        pm_mod = importlib.import_module("product_matcher")
        cls = getattr(pm_mod, "ProductMatcher")
        matcher = getattr(__import__("main"), "PRODUCT_MATCHER", None)

        clean = getattr(pm_mod, "catalog_clean_text", None)
        key = getattr(pm_mod, "catalog_variant_key", None)

        out["runtime"] = {
            "product_matcher_file": getattr(pm_mod, "__file__", ""),
            "product_matcher_sha256": hashlib.sha256(
                Path(getattr(pm_mod, "__file__")).read_bytes()
            ).hexdigest() if getattr(pm_mod, "__file__", None) and Path(getattr(pm_mod, "__file__")).exists() else "",
            "catalog_clean_text_source": inspect.getsource(clean) if clean else None,
            "catalog_variant_key_source": inspect.getsource(key) if key else None,
            "matcher_type": type(matcher).__name__ if matcher else None,
        }

        samples = [
            ("UOMO_Deloox", "Valentino Born in Roma Ivory Uomo Eau de Toilette Limited edition 100 ml"),
            ("DONNA_Deloox", "Valentino Donna Born in Roma Ivory Eau de Parfum Limited edition 100 ml"),
            ("UOMO_canonical", "Born in Roma Uomo Ivory"),
            ("UOMO_alias", "Born in Roma Ivory Uomo"),
            ("DONNA_canonical", "Born in Roma Donna Ivory"),
            ("DONNA_alias", "Born in Roma Ivory Donna"),
            ("DONNA_alias_edp", "Born in Roma Ivory Eau de Parfum Donna"),
        ]

        out["keys"] = []
        for label, value in samples:
            item = {"label": label, "input": value}
            try:
                item["clean"] = clean(value) if clean else None
            except Exception as exc:
                item["clean_error"] = f"{type(exc).__name__}: {exc}"
            try:
                item["variant_key"] = key(value) if key else None
            except Exception as exc:
                item["key_error"] = f"{type(exc).__name__}: {exc}"
            out["keys"].append(item)

        # Re-run the exact family offer resolution with the live matcher.
        family = None
        if matcher is not None and hasattr(matcher, "_family_for_query"):
            family = matcher._family_for_query(q)
        out["family_id"] = family.get("family_id") if isinstance(family, dict) else None

        out["variant_resolution"] = []
        if isinstance(family, dict) and hasattr(matcher, "_family_variant_for_offer"):
            for label, value in samples[:2]:
                offer = {
                    "brand": "Valentino",
                    "name": value,
                    "store": "Deloox",
                    "url": (
                        "https://www.deloox.be/produit/1400167/valentino-born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html"
                        if label == "UOMO_Deloox"
                        else "https://www.deloox.be/produit/1400164/valentino-donna-born-in-roma-ivory-eau-de-parfum-limited-edition-100-ml.html"
                    ),
                    "price": "100,49 €" if label == "UOMO_Deloox" else "121,59 €",
                    "price_num": 100.49 if label == "UOMO_Deloox" else 121.59,
                    "size_ml": 100.0,
                }
                try:
                    resolved = matcher._family_variant_for_offer(offer, family)
                    out["variant_resolution"].append({
                        "label": label,
                        "resolved": resolved,
                    })
                except Exception as exc:
                    out["variant_resolution"].append({
                        "label": label,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    })

        return out

    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        return out
