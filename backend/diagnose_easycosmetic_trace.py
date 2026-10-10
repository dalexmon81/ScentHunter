# ScentHunter — unico diagnostico Easycosmetic formato
# Da inserire in backend/main.py prima della route @app.get('/frontend').
# Endpoint in sola lettura: /diagnose-easycosmetic-trace?store=easycosmetic&q=Valentino%20Born%20in%20Roma%20Coral%20Fantasy
#
# Nota: questo file contiene la route completa da aggiungere, non è un main.py
# completo. Non sostituisce il file backend/main.py.

@app.get("/diagnose-easycosmetic-trace")
def diagnose_easycosmetic_trace(
    store: str = "easycosmetic",
    q: str = "Valentino Born in Roma Coral Fantasy",
):
    """Traccia read-only ogni candidato del catalogo attraverso gli stadi finali."""
    query = str(q or "").strip()
    store_key = _normalise_store(store, "")

    if not query:
        return {"ok": False, "diagnostic": "easycosmetic-trace-v1", "error": "missing_query"}
    if not store_key or store_key not in STORES:
        return {
            "ok": False,
            "diagnostic": "easycosmetic-trace-v1",
            "error": "unknown_store",
            "store": store,
            "known_stores": list(STORES),
        }
    if not CATALOG_ENGINE_AVAILABLE or not callable(catalog_search_local):
        return {
            "ok": False,
            "diagnostic": "easycosmetic-trace-v1",
            "read_only": True,
            "error": "catalog_engine_unavailable",
        }

    def snapshot(item):
        if not isinstance(item, dict):
            return {"type": type(item).__name__, "value": repr(item)[:300]}
        keys = (
            "store", "store_key", "name", "title", "_raw_name",
            "brand", "_raw_brand", "size_ml", "concentration", "gender",
            "price", "currency", "availability", "url", "product_url",
            "sku", "gtin", "mpn", "category", "category_name",
            "product_type", "is_fragrance", "is_perfume",
            "catalog_id", "canonical_name", "_match_status",
            "_match_method", "match_method", "_match_score", "match_score",
        )
        return {key: item.get(key) for key in keys if key in item}

    try:
        # Stessa ricerca locale sul catalogo persistente usata dalla ricerca
        # normale; nessun refresh, sync, hydration o aggiornamento DB.
        raw_candidates = catalog_search_local(query, per_store=32)
    except Exception as exc:
        return {
            "ok": False,
            "diagnostic": "easycosmetic-trace-v1",
            "read_only": True,
            "store": store_key,
            "query": query,
            "error": "catalog_search_local_failed",
            "exception": f"{type(exc).__name__}: {exc}",
        }

    if not isinstance(raw_candidates, list):
        raw_candidates = []

    candidates = []
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        candidate_store = _normalise_store(
            raw.get("store_key") or raw.get("store") or raw.get("shop"), ""
        )
        if candidate_store != store_key:
            continue

        row = {
            "catalog_candidate": snapshot(raw),
            "stages": [],
            "loss_point": None,
            "cleaned": None,
            "matcher_result": None,
            "final_eligible": False,
        }

        try:
            prepared = clean_result(raw, store_key)
        except Exception as exc:
            row["stages"].append({
                "stage": "clean_result",
                "outcome": "exception",
                "exception": f"{type(exc).__name__}: {exc}",
            })
            row["loss_point"] = "clean_result_exception"
            candidates.append(row)
            continue

        if prepared is None:
            row["stages"].append({"stage": "clean_result", "outcome": "dropped_none"})
            row["loss_point"] = "clean_result_returned_none"
            candidates.append(row)
            continue

        row["cleaned"] = snapshot(prepared)
        row["stages"].append({"stage": "clean_result", "outcome": "kept"})
        try:
            pre_match_non_fragrance = _is_non_fragrance_offer(prepared)
        except Exception as exc:
            row["stages"].append({
                "stage": "non_fragrance_filter_before_match",
                "outcome": "exception",
                "exception": f"{type(exc).__name__}: {exc}",
            })
            row["loss_point"] = "non_fragrance_filter_before_match_exception"
            candidates.append(row)
            continue

        row["stages"].append({
            "stage": "non_fragrance_filter_before_match",
            "outcome": "rejected" if pre_match_non_fragrance else "kept",
        })
        if pre_match_non_fragrance:
            row["loss_point"] = "non_fragrance_filter_before_match"
            candidates.append(row)
            continue

        try:
            resolved = _resolve_offer_identity(prepared, query)
        except Exception as exc:
            row["stages"].append({
                "stage": "ProductMatcher",
                "outcome": "exception",
                "exception": f"{type(exc).__name__}: {exc}",
            })
            row["loss_point"] = "ProductMatcher_exception"
            candidates.append(row)
            continue

        if not isinstance(resolved, dict):
            row["stages"].append({
                "stage": "ProductMatcher",
                "outcome": "returned_non_dict",
                "returned_type": type(resolved).__name__,
            })
            row["loss_point"] = "ProductMatcher_returned_non_dict"
            candidates.append(row)
            continue

        row["matcher_result"] = snapshot(resolved)
        row["stages"].append({
            "stage": "ProductMatcher",
            "outcome": resolved.get("_match_status") or "status_missing",
            "catalog_id": resolved.get("catalog_id"),
            "canonical_name": resolved.get("canonical_name"),
            "size_ml": resolved.get("size_ml"),
        })

        if resolved.get("_match_status") == "rejected":
            row["loss_point"] = "ProductMatcher_rejected"
            candidates.append(row)
            continue

        try:
            post_match_non_fragrance = _is_non_fragrance_offer(resolved)
        except Exception as exc:
            row["stages"].append({
                "stage": "non_fragrance_filter_after_match",
                "outcome": "exception",
                "exception": f"{type(exc).__name__}: {exc}",
            })
            row["loss_point"] = "non_fragrance_filter_after_match_exception"
            candidates.append(row)
            continue

        row["stages"].append({
            "stage": "non_fragrance_filter_after_match",
            "outcome": "rejected" if post_match_non_fragrance else "kept",
        })
        if post_match_non_fragrance:
            row["loss_point"] = "non_fragrance_filter_after_match"
            candidates.append(row)
            continue

        row["final_eligible"] = True
        if resolved.get("_match_status") != "matched" or not resolved.get("catalog_id"):
            row["loss_point"] = "survived_but_unresolved"
        else:
            row["loss_point"] = None
        candidates.append(row)

    return {
        "ok": True,
        "diagnostic": "easycosmetic-trace-v1",
        "read_only": True,
        "writes_database": False,
        "sync_or_refresh_called": False,
        "production_search_called": False,
        "store": store_key,
        "query": query,
        "pipeline": [
            "catalog_search_local",
            "clean_result",
            "non_fragrance_filter_before_match",
            "ProductMatcher",
            "non_fragrance_filter_after_match",
        ],
        "candidate_count_for_store": len(candidates),
        "eligible_count": sum(1 for item in candidates if item["final_eligible"]),
        "lost_by_stage": {
            stage: sum(1 for item in candidates if item["loss_point"] == stage)
            for stage in (
                "clean_result_returned_none",
                "clean_result_exception",
                "non_fragrance_filter_before_match",
                "non_fragrance_filter_before_match_exception",
                "ProductMatcher_returned_non_dict",
                "ProductMatcher_exception",
                "ProductMatcher_rejected",
                "non_fragrance_filter_after_match",
                "non_fragrance_filter_after_match_exception",
                "survived_but_unresolved",
            )
        },
        "candidates": candidates,
        "interpretation": (
            "Il report mostra i candidati attualmente presenti nel catalogo persistente. "
            "Non può ricostruire valori storici già sovrascritti se non esistono log o versioni precedenti."
        ),
    }
