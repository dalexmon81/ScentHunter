# ScentHunter — diagnostica read-only Easycosmetic refresh handoff
# Destinazione: backend/diagnose_easycosmetic_refresh_handoff.py
#
# Questo file contiene una funzione di diagnostica richiamabile da main.py.
# Non chiama refresh_url(), non scrive su SQLite e non modifica la coda.

def diagnose_easycosmetic_refresh_handoff():
    """Read-only: verifica il passaggio live HTML -> parser usato da refresh_url."""
    import importlib
    from urllib.parse import urlparse

    targets = [
        {
            "label": "donna",
            "url": "https://www.easycosmetic.de/valentino/donna-born-in-roma/valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx",
        },
        {
            "label": "uomo",
            "url": "https://www.easycosmetic.de/valentino/uomo-born-in-roma/valentino-uomo-born-in-roma-coral-fantasy-eau-de-toilette-spray.aspx",
        },
    ]

    report = {
        "ok": True,
        "diagnostic": "easycosmetic-refresh-handoff-v1",
        "read_only": True,
        "database_writes": False,
        "refresh_url_called": False,
        "hydration_queue_touched": False,
        "purpose": (
            "Verifica il percorso http_get -> _secondary_store_parser con lo stesso "
            "page_html passato da refresh_url, senza eseguire la persistenza."
        ),
        "products": [],
    }

    try:
        engine = importlib.import_module("catalog_engine")
        http_get = getattr(engine, "http_get", None)
        parser = getattr(engine, "_secondary_store_parser", None)
        url_slug = getattr(engine, "url_slug", None)
        if not callable(http_get) or not callable(parser) or not callable(url_slug):
            return {
                **report,
                "ok": False,
                "error": "required_catalog_engine_function_unavailable",
                "functions": {
                    "http_get": callable(http_get),
                    "_secondary_store_parser": callable(parser),
                    "url_slug": callable(url_slug),
                },
            }
    except Exception as exc:
        return {
            **report,
            "ok": False,
            "error": "catalog_engine_import_failed",
            "exception": f"{type(exc).__name__}: {str(exc)[:500]}",
        }

    def compact(value):
        if not isinstance(value, dict):
            return {"type": type(value).__name__, "value": repr(value)[:300]}
        keys = (
            "store", "store_key", "url", "name", "brand", "size_ml",
            "concentration", "gender", "image", "sku", "gtin", "mpn",
            "price_num", "price", "currency", "availability", "available",
        )
        return {key: value.get(key) for key in keys if key in value}

    for target in targets:
        entry = {"label": target["label"], "requested_url": target["url"], "stages": {}}
        parsed_url = urlparse(target["url"])
        if parsed_url.scheme != "https" or parsed_url.hostname != "www.easycosmetic.de":
            entry["error"] = "url_not_allowed"
            report["products"].append(entry)
            continue
        try:
            status, final_url, page_html = http_get(target["url"], timeout=18)
            entry["stages"]["http_get"] = {
                "http_status": status,
                "final_url": final_url,
                "html_type": type(page_html).__name__,
                "html_bytes": len(page_html or b""),
            }
            if status >= 400:
                entry["error"] = f"http_status_{status}"
                report["products"].append(entry)
                continue

            parsed = parser(
                "easycosmetic", final_url, target["url"], page_html=page_html
            )
            entry["stages"]["_secondary_store_parser"] = compact(parsed)
            if isinstance(parsed, dict):
                entry["comparison"] = {
                    "parsed_size_ml": parsed.get("size_ml"),
                    "parsed_image": parsed.get("image"),
                    "parsed_price_num": parsed.get("price_num"),
                    "parsed_name": parsed.get("name"),
                    "has_product_name": bool(parsed.get("name")),
                    "refresh_url_would_accept_parser_result": bool(parsed.get("name")),
                }
            else:
                entry["comparison"] = {
                    "returned_type": type(parsed).__name__,
                    "refresh_url_would_accept_parser_result": False,
                }
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        report["products"].append(entry)
    return report
