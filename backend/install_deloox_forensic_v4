from pathlib import Path
import ast

TARGET = Path("backend/search_engine.py")
MARKER = "SCENTHUNTER_DELOOX_FORENSIC_V4"

HELPERS = """
# ============================================================
# DELOOX / LIQUID BRUN FORENSIC V4 - READ ONLY
# ============================================================
DELOOX_FORENSIC_MARKER = "SCENTHUNTER_DELOOX_FORENSIC_V4"

def _forensic_enabled(query):
    return str(query or "").strip().casefold() == "liquid brun"

def _forensic_emit(stage, query, **extra):
    if not _forensic_enabled(query):
        return
    payload = {"marker": DELOOX_FORENSIC_MARKER, "stage": stage,
               "query": str(query or ""), **extra}
    print(DELOOX_FORENSIC_MARKER + " " +
          json.dumps(payload, ensure_ascii=False, default=str), flush=True)

def _forensic_deloox(items):
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        store = str(item.get("store") or item.get("shop") or "").strip().casefold()
        url = str(item.get("url") or "").strip().casefold()
        if store != "deloox" and "deloox" not in url:
            continue
        out.append({
            "store": item.get("store"),
            "name": item.get("name") or item.get("title") or item.get("product_name"),
            "brand": item.get("brand") or item.get("source_brand") or item.get("canonical_brand"),
            "size_ml": item.get("size_ml") or item.get("volume_ml") or item.get("size") or item.get("format") or item.get("volume"),
            "price": item.get("price") if item.get("price") is not None else item.get("price_num"),
            "availability": item.get("availability") or item.get("stock_status") or item.get("stock"),
            "in_stock": item.get("in_stock") if "in_stock" in item else item.get("available"),
            "url": item.get("url"),
            "source": item.get("source"),
            "canonical_name": item.get("canonical_name"),
            "catalog_variant": item.get("catalog_variant"),
            "family_id": item.get("family_id"),
        })
    return out

def _forensic_sig(item):
    return "|".join(str(item.get(k) or "").strip().casefold()
                    for k in ("store", "url", "name", "size_ml"))
"""

METHOD = """
    def _install_deloox_forensic_v4(self):
        if getattr(self, "_deloox_forensic_v4", False):
            return
        self._deloox_forensic_v4 = True
        legacy = self.legacy

        original_filter = self._filter_requested_format
        def traced_filter(candidates, query):
            before = list(candidates or [])
            after = original_filter(candidates, query)
            if _forensic_enabled(query):
                b, a = _forensic_deloox(before), _forensic_deloox(after)
                after_sigs = {_forensic_sig(x) for x in a}
                _forensic_emit(
                    "STAGE_3A_FILTER", query,
                    before_deloox_count=len(b), before_deloox=b,
                    after_deloox_count=len(a), after_deloox=a,
                    removed=[x for x in b if _forensic_sig(x) not in after_sigs],
                )
            return after
        self._filter_requested_format = traced_filter

        original_pre = getattr(legacy, "_pre_rank_candidates", None)
        if callable(original_pre):
            def traced_pre(candidates, query, _orig=original_pre):
                before = list(candidates or [])
                try:
                    after = _orig(candidates, query)
                except TypeError:
                    after = _orig(candidates)
                if _forensic_enabled(query):
                    b, a = _forensic_deloox(before), _forensic_deloox(after)
                    after_sigs = {_forensic_sig(x) for x in a}
                    _forensic_emit(
                        "STAGE_3B_PRE_RANK", query,
                        before_deloox_count=len(b), before_deloox=b,
                        after_deloox_count=len(a), after_deloox=a,
                        removed=[x for x in b if _forensic_sig(x) not in after_sigs],
                    )
                return after
            legacy._pre_rank_candidates = traced_pre

        original_validate = getattr(legacy, "_validate_candidates_parallel", None)
        original_one = getattr(legacy, "_validate_candidate", None)

        if callable(original_validate):
            def traced_validate(candidates, query, _orig=original_validate):
                before = list(candidates or [])
                if _forensic_enabled(query):
                    _forensic_emit(
                        "STAGE_3C_VALIDATION_INPUT", query,
                        input_count=len(before),
                        deloox_count=len(_forensic_deloox(before)),
                        deloox=_forensic_deloox(before),
                    )
                try:
                    after = _orig(candidates, query)
                except TypeError:
                    after = _orig(candidates)
                after = list(after or [])
                if _forensic_enabled(query):
                    _forensic_emit(
                        "STAGE_3C_VALIDATION_OUTPUT", query,
                        output_count=len(after),
                        deloox_count=len(_forensic_deloox(after)),
                        deloox=_forensic_deloox(after),
                    )
                return after
            legacy._validate_candidates_parallel = traced_validate

        if callable(original_one) and not getattr(original_one, "_deloox_forensic_v4", False):
            original_matches = getattr(legacy, "matches", None)
            original_catalog = getattr(legacy, "_catalog_match", None)

            if callable(original_matches):
                def traced_matches(product, query, _orig=original_matches):
                    result = _orig(product, query)
                    if (_forensic_enabled(query) and
                        str(product.get("store") or product.get("shop") or "").strip().casefold() == "deloox"):
                        _forensic_emit("STAGE_3C_MATCHES", query,
                                       candidate=_forensic_deloox([product]),
                                       result=bool(result))
                    return result
                legacy.matches = traced_matches

            if callable(original_catalog):
                def traced_catalog(product, query, _orig=original_catalog):
                    try:
                        result = _orig(product, query)
                    except Exception as exc:
                        if (_forensic_enabled(query) and
                            str(product.get("store") or product.get("shop") or "").strip().casefold() == "deloox"):
                            _forensic_emit("STAGE_3C_CATALOG_EXCEPTION", query,
                                           candidate=_forensic_deloox([product]),
                                           exception_type=type(exc).__name__,
                                           exception=str(exc))
                        raise
                    if (_forensic_enabled(query) and
                        str(product.get("store") or product.get("shop") or "").strip().casefold() == "deloox"):
                        _forensic_emit("STAGE_3C_CATALOG_MATCH", query,
                                       candidate=_forensic_deloox([product]),
                                       result=result)
                    return result
                legacy._catalog_match = traced_catalog

            def traced_one(product, query, _orig=original_one):
                is_deloox = (
                    isinstance(product, dict) and
                    str(product.get("store") or product.get("shop") or "").strip().casefold() == "deloox"
                )
                if not _forensic_enabled(query) or not is_deloox:
                    return _orig(product, query)
                _forensic_emit("STAGE_3C_CANDIDATE_BEFORE", query,
                               candidate=_forensic_deloox([product]))
                try:
                    result = _orig(product, query)
                except Exception as exc:
                    _forensic_emit("STAGE_3C_CANDIDATE_EXCEPTION", query,
                                   candidate=_forensic_deloox([product]),
                                   exception_type=type(exc).__name__,
                                   exception=str(exc))
                    raise
                _forensic_emit(
                    "STAGE_3C_CANDIDATE_AFTER", query,
                    candidate=_forensic_deloox([product]),
                    result=_forensic_deloox([result]) if isinstance(result, dict) else None,
                    outcome="validated" if isinstance(result, dict) else "REJECTED_OR_NONE",
                )
                return result
            traced_one._deloox_forensic_v4 = True
            legacy._validate_candidate = traced_one

        original_prepare = getattr(legacy, "_prepare_final_results", None)
        if callable(original_prepare):
            def traced_prepare(products, query=None, _orig=original_prepare):
                if _forensic_enabled(query):
                    _forensic_emit("STAGE_4_PREPARE_INPUT", query,
                                   input_count=len(products or []),
                                   deloox_count=len(_forensic_deloox(products)),
                                   deloox=_forensic_deloox(products))
                try:
                    out = _orig(products, query)
                except TypeError:
                    out = _orig(products)
                if _forensic_enabled(query):
                    nested = []
                    for item in out or []:
                        if isinstance(item, dict) and isinstance(item.get("offers"), list):
                            nested.extend(_forensic_deloox(item["offers"]))
                    _forensic_emit("STAGE_4_PREPARE_OUTPUT", query,
                                   output_count=len(out or []),
                                   deloox_count=len(_forensic_deloox(out)),
                                   deloox=_forensic_deloox(out),
                                   deloox_nested_offers=nested)
                return out
            legacy._prepare_final_results = traced_prepare
"""

s = TARGET.read_text(encoding="utf-8")
if MARKER in s:
    raise SystemExit("Forensic V4 already installed")
if "import json\n" not in s:
    raise SystemExit("Expected import json not found")

anchor = "\n\n@dataclass\nclass StoreRun:"
if anchor not in s:
    raise SystemExit("StoreRun anchor not found")
s = s.replace(anchor, HELPERS + anchor, 1)

anchor = "            ]\n\n    # ------------------------------------------------------------------\n    # Query analysis"
if anchor not in s:
    raise SystemExit("SearchEngine __init__ anchor not found")
s = s.replace(
    anchor,
    "            ]\n\n        self._install_deloox_forensic_v4()\n\n" +
    METHOD +
    "    # ------------------------------------------------------------------\n    # Query analysis",
    1,
)

anchor = "                        raw_pool.extend(result.candidates)\n\n                        if _trace_enabled(query):"
if anchor not in s:
    raise SystemExit("run_job raw_pool anchor not found")
s = s.replace(
    anchor,
    """                        raw_pool.extend(result.candidates)

                        if _forensic_enabled(query):
                            _forensic_emit(
                                "STAGE_2_RAW_POOL", query, job_id=job_id,
                                completed_store=store,
                                raw_pool_count=len(raw_pool),
                                deloox_count=len(_forensic_deloox(raw_pool)),
                                deloox=_forensic_deloox(raw_pool),
                            )

                        if _trace_enabled(query):""",
    1,
)

anchor = """            validated = self._validate_candidates_only(query, raw_pool)
            update({
                "results": validated,"""
if anchor not in s:
    raise SystemExit("final job update anchor not found")
s = s.replace(
    anchor,
    """            validated = self._validate_candidates_only(query, raw_pool)
            if _forensic_enabled(query):
                _forensic_emit(
                    "STAGE_5_JOB_STATE_BEFORE_SAVE", query, job_id=job_id,
                    validated_count=len(validated),
                    deloox_count=len(_forensic_deloox(validated)),
                    deloox=_forensic_deloox(validated),
                )
            update({
                "results": validated,""",
    1,
)

ast.parse(s)
TARGET.write_text(s, encoding="utf-8")
print("Installed SCENTHUNTER_DELOOX_FORENSIC_V4")
