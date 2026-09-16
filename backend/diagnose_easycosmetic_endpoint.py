"""
ScentHunter — Easycosmetic focused diagnostic
Diagnostic only. Does not modify matching, scrapers, ProductMatcher,
family_registry, or frontend.

Endpoint:
  /diagnose-easycosmetic?q=Liquid%20Brun

This endpoint runs ONLY Easycosmetic and has a hard deadline.
"""
from fastapi import APIRouter
import importlib
import time
import inspect

router = APIRouter()

MAX_SECONDS = 35
MAX_CANDIDATES = 30


def _main():
    return importlib.import_module("main")


def _source(main):
    try:
        lines, start = inspect.getsourcelines(main.matches)
        return {"start": start, "source": "".join(lines)}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _trace(main, product, query):
    info = _source(main)
    by_line = {}
    if "start" in info:
        for i, line in enumerate(info["source"].splitlines()):
            by_line[info["start"] + i] = line.strip()

    target = main.matches.__code__
    result = {"value": None, "return_line": None, "return_source": "",
              "locals": {}, "lines": []}

    def tracer(frame, event, arg):
        if frame.f_code is target:
            if event == "line":
                if frame.f_lineno not in result["lines"]:
                    result["lines"].append(frame.f_lineno)
            elif event == "return":
                result["value"] = bool(arg)
                result["return_line"] = frame.f_lineno
                result["return_source"] = by_line.get(frame.f_lineno, "")
                result["locals"] = {
                    k: repr(v)[:500]
                    for k, v in frame.f_locals.items()
                    if k != "product"
                }
        return tracer

    old = __import__("sys").gettrace()
    try:
        __import__("sys").settrace(tracer)
        value = main.matches(product, query)
    finally:
        __import__("sys").settrace(old)

    result["value"] = bool(value)
    return result


@router.get("/diagnose-easycosmetic")
def diagnose_easycosmetic(q: str = "Liquid Brun"):
    main = _main()
    query = str(q or "").strip() or "Liquid Brun"
    started = time.monotonic()

    module = main.load_scraper("easycosmetic")
    search_fn = getattr(module, "search", None)
    if not callable(search_fn):
        search_fn = getattr(module, "scrape", None)

    attempts = main.build_search_attempts("easycosmetic", query)
    raw = []
    errors = []

    for attempt in attempts:
        if time.monotonic() - started > MAX_SECONDS:
            break
        try:
            values = search_fn(attempt) or []
            if isinstance(values, list):
                raw.extend(values)
        except Exception as exc:
            errors.append({
                "stage": "search",
                "attempt": attempt,
                "error": f"{type(exc).__name__}: {exc}"
            })

    unique = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        product = dict(item)
        product.setdefault("store", "easycosmetic")
        key = main.product_identity_key(product)
        if key in seen:
            continue
        seen.add(key)
        product = main.resolve_actual_price(product)
        image = main.product_image(product)
        if image:
            product["image"] = image
        unique.append(product)

    tested = []
    accepted = 0

    for i, product in enumerate(unique[:MAX_CANDIDATES]):
        if time.monotonic() - started > MAX_SECONDS:
            break

        trace = _trace(main, product, query)
        if trace["value"]:
            accepted += 1

        search_text = main.product_search_text(product)
        tested.append({
            "index": i,
            "name": product.get("name", ""),
            "title": product.get("title", ""),
            "brand": product.get("brand", ""),
            "size_ml": main.product_size_ml(product),
            "concentration": (
                main.product_concentration(product)
                if hasattr(main, "product_concentration") else ""
            ),
            "url": product.get("url", ""),
            "query_token_hits": {
                token: token in search_text.lower()
                for token in query.lower().split()
            },
            "matches": trace,
        })

    return {
        "diagnostic": True,
        "version": "easycosmetic_only_v1",
        "query": query,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "attempts": attempts,
        "raw": len(raw),
        "unique": len(unique),
        "tested": len(tested),
        "accepted": accepted,
        "errors": errors,
        "candidates": tested,
        "deadline_sec": MAX_SECONDS
    }
