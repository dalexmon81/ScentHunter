"""
ScentHunter - Point 1 - Notino discovery diagnostic

NON modifica lo scraper Notino.
NON modifica main.py.
Serve solo a capire dove vengono persi i candidati.

Per ogni query misura separatamente:
1. HTTP discovery
2. Browser discovery
3. fusione/deduplicazione
4. parse_search_candidate
5. risultato finale

Il report viene salvato in:
    notino_diagnostic_report.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

notino = importlib.import_module("scrapers.notino.scraper")


def short(value: Any) -> str:
    return str(value or "").strip()


def candidate_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    url = short(item.get("url"))
    return {
        "name": short(item.get("name")),
        "brand": short(item.get("brand")),
        "url": url,
        "score": item.get("score"),
        "size_ml": item.get("size_ml"),
        "concentration": item.get("concentration"),
        "availability": item.get("availability"),
        "product_key": (
            notino.product_key(url)
            if url and hasattr(notino, "product_key")
            else ""
        ),
    }


def product_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": short(item.get("name")),
        "brand": short(
            (item.get("source") or {}).get("source_brand")
            if isinstance(item.get("source"), dict)
            else item.get("brand")
        ),
        "url": short(item.get("url")),
        "price": short(item.get("price")),
        "available": item.get("available"),
        "size_ml": (
            ((item.get("attributes") or {}).get("size_ml") or {}).get("value")
            if isinstance(item.get("attributes"), dict)
            else None
        ),
        "concentration": (
            ((item.get("attributes") or {}).get("concentration") or {}).get("value")
            if isinstance(item.get("attributes"), dict)
            else None
        ),
    }


def run_channel(name: str, fn, query: str) -> Dict[str, Any]:
    started = time.perf_counter()
    report = {
        "channel": name,
        "status": "ok",
        "elapsed_seconds": 0.0,
        "count": 0,
        "candidates": [],
    }

    try:
        items = fn(query) or []
        if not isinstance(items, list):
            items = []

        report["count"] = len(items)
        report["candidates"] = [
            candidate_summary(x)
            for x in items
            if isinstance(x, dict)
        ]
    except Exception as exc:
        report["status"] = "error"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()

    report["elapsed_seconds"] = round(
        time.perf_counter() - started, 3
    )
    return report


def run_query(query: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "query": query,
        "status": "ok",
        "channels": {},
        "merged_candidates": [],
        "parsed_candidates": [],
        "rejected_candidates": [],
        "final_search_results": [],
    }

    http_report = run_channel(
        "http_discover",
        notino.http_discover,
        query,
    )
    browser_report = run_channel(
        "browser_discover",
        notino.browser_discover,
        query,
    )

    report["channels"]["http_discover"] = http_report
    report["channels"]["browser_discover"] = browser_report

    merged: List[Dict[str, Any]] = []
    seen = set()

    for source_name, channel in (
        ("http", http_report),
        ("browser", browser_report),
    ):
        for item in channel.get("candidates", []):
            url = short(item.get("url"))
            key = (
                notino.product_key(url)
                if url
                else ""
            )
            if not key:
                key = f"url:{url}"

            if key in seen:
                continue

            seen.add(key)

            merged.append({
                **item,
                "discovery_channel": source_name,
                "dedupe_key": key,
            })

    report["merged_candidates"] = merged

    parser_fn = getattr(notino, "parse_search_candidate", None)

    if not callable(parser_fn):
        report["status"] = "error"
        report["error"] = "parse_search_candidate non disponibile"
        return report

    for item in merged:
        raw = dict(item)

        try:
            parsed = parser_fn(raw, query)
        except Exception as exc:
            report["rejected_candidates"].append({
                "candidate": candidate_summary(raw),
                "reason": f"{type(exc).__name__}: {exc}",
                "stage": "parse_search_candidate_exception",
            })
            continue

        if parsed:
            report["parsed_candidates"].append({
                "candidate": candidate_summary(raw),
                "result": product_summary(parsed),
            })
        else:
            # Eseguiamo i controlli elementari separatamente per capire
            # quale condizione sta probabilmente eliminando il candidato.
            name = short(raw.get("name"))
            brand = short(raw.get("brand"))
            size_ml = raw.get("size_ml")

            checks = {}

            for fn_name, fn_args in (
                ("product_url", (raw.get("url"),)),
                ("query_matches", (name, brand, query, size_ml)),
            ):
                fn = getattr(notino, fn_name, None)
                if callable(fn):
                    try:
                        checks[fn_name] = bool(fn(*fn_args))
                    except Exception as exc:
                        checks[fn_name] = f"{type(exc).__name__}: {exc}"

            report["rejected_candidates"].append({
                "candidate": candidate_summary(raw),
                "checks": checks,
                "reason": "parse_search_candidate_returned_none",
                "stage": "parse_search_candidate",
            })

    # Ricostruiamo esattamente ciò che search() restituisce, ma senza
    # richiamare search(), così il report resta separato dalla logica reale.
    final = []
    seen_final = set()

    for item in report["parsed_candidates"]:
        result = item["result"]
        key = notino.product_key(result.get("url"))

        if not key or key in seen_final:
            continue

        seen_final.add(key)
        final.append(result)

    report["final_search_results"] = final

    return report


def print_report(report: Dict[str, Any]) -> None:
    print()
    print("=" * 72)
    print("NOTINO - POINT 1 DIAGNOSTICA")
    print(f"QUERY: {report['query']}")
    print()

    for channel_name in ("http_discover", "browser_discover"):
        channel = report["channels"].get(channel_name, {})
        print(
            f"{channel_name}: "
            f"{channel.get('count', 0)} candidati | "
            f"{channel.get('elapsed_seconds', 0):.3f}s | "
            f"{channel.get('status')}"
        )

    print(
        f"CANDIDATI DOPO FUSIONE: "
        f"{len(report['merged_candidates'])}"
    )
    print(
        f"CANDIDATI ACCETTATI DAL PARSER: "
        f"{len(report['parsed_candidates'])}"
    )
    print(
        f"CANDIDATI SCARTATI DAL PARSER: "
        f"{len(report['rejected_candidates'])}"
    )
    print(
        f"RISULTATI FINALI: "
        f"{len(report['final_search_results'])}"
    )

    print()
    print("CANDIDATI TROVATI:")
    for item in report["merged_candidates"]:
        print(
            f"  [{item.get('discovery_channel')}] "
            f"{item.get('name') or '-'} | "
            f"{item.get('url') or '-'}"
        )

    print()
    print("SCARTI:")
    for item in report["rejected_candidates"]:
        candidate = item.get("candidate", {})
        print(
            f"  - {candidate.get('name') or '-'} | "
            f"{candidate.get('url') or '-'} | "
            f"checks={item.get('checks', {})}"
        )

    print()
    print("RISULTATI:")
    for item in report["final_search_results"]:
        print(
            f"  - {item.get('name') or '-'} | "
            f"{item.get('price') or '-'} | "
            f"{item.get('url') or '-'}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument(
        "--output",
        default=os.path.join(
            CURRENT_DIR,
            "notino_diagnostic_report.json",
        ),
    )
    args = parser.parse_args()

    query = short(args.query)
    if not query:
        raise SystemExit("Query vuota.")

    report = run_query(query)

    with open(
        os.path.abspath(args.output),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            report,
            handle,
            ensure_ascii=False,
            indent=2,
        )

    print_report(report)


if __name__ == "__main__":
    main()
