import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUERY = "Miu Miu"

def pname(p):
    return str(p.get("name") or p.get("title") or p.get("product_name") or "")

def main():
    lines = ["=== SCENTHUNTER PIPELINE DIAGNOSTIC ===", f"QUERY: {QUERY}", ""]

    try:
        mainmod = importlib.import_module("backend.main")
    except ModuleNotFoundError:
        mainmod = importlib.import_module("main")

    try:
        sabina = importlib.import_module("backend.scrapers.sabina.scraper")
    except ModuleNotFoundError:
        sabina = importlib.import_module("scrapers.sabina.scraper")

    raw = sabina.search(QUERY) or []
    lines.append(f"SABINA SCRAPER COUNT: {len(raw)}")
    for i, p in enumerate(raw, 1):
        lines.append(f"S{i}: {pname(p)} | {p.get('price')} | {p.get('url')}")

    lines.append("")
    perfume = [p for p in raw if isinstance(p, dict) and mainmod.is_perfume(p)]
    lines.append(f"AFTER is_perfume: {len(perfume)}")

    relevant = [p for p in perfume if mainmod.query_relevant(p, QUERY)]
    lines.append(f"AFTER query_relevant: {len(relevant)}")

    priced = [p for p in relevant if mainmod.price_value(p) != float("inf")]
    lines.append(f"AFTER price filter: {len(priced)}")

    cleaned, comparisons = mainmod.enrich_and_group(raw, QUERY)
    lines.append(f"AFTER enrich_and_group results: {len(cleaned)}")
    lines.append(f"COMPARISONS COUNT: {len(comparisons)}")
    lines.append("")

    lines.append("=== CLEANED RESULTS ===")
    for i, p in enumerate(cleaned, 1):
        lines.append(
            f"R{i}: {pname(p)} | key={p.get('comparison_key')} | "
            f"{p.get('price')} | {p.get('url')}"
        )

    lines.append("")
    lines.append("=== COMPARISONS ===")
    for i, c in enumerate(comparisons, 1):
        lines.append(
            f"C{i}: {c.get('name')} | key={c.get('key')} | "
            f"offers={c.get('offer_count')} | best={c.get('best_price')}"
        )

    lines.append("")
    lines.append("=== FULL /search FUNCTION ===")
    try:
        response = mainmod.search_perfume(QUERY)
        sabina_results = [
            p for p in response.get("results", [])
            if str(p.get("store", "")).lower() == "sabina"
        ]
        lines.append(f"HTTP FUNCTION TOTAL RESULTS: {response.get('count')}")
        lines.append(f"HTTP FUNCTION SABINA RESULTS: {len(sabina_results)}")
        lines.append(f"HTTP FUNCTION COMPARISONS: {response.get('comparison_count')}")
        for i, p in enumerate(sabina_results, 1):
            lines.append(f"H{i}: {pname(p)} | {p.get('price')} | {p.get('url')}")
    except Exception as e:
        lines.append(f"FULL SEARCH ERROR: {type(e).__name__}: {e}")

    report = "\n".join(lines)
    out = Path(__file__).resolve().parent / "scenthunter_pipeline_report.txt"
    out.write_text(report, encoding="utf-8")
    print(report)
    print("\nREPORT SAVED:", out)

if __name__ == "__main__":
    main()
