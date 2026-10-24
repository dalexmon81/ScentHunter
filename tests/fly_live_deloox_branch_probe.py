"""Read-only live Deloox parser probe executed inside the Fly app network.

The probe intentionally performs bounded HTTP reads only. It never imports the
application catalog engine or opens its production database.
"""
import hashlib
import json
import sys
import types
import urllib.request

import requests

sha = sys.argv[1]
base = f"https://raw.githubusercontent.com/dalexmon81/ScentHunter/{sha}/backend/scrapers/deloox/scraper.py"

report = {
    "branch_sha": sha,
    "read_only": True,
    "database_mutated": False,
    "parser_source_url": base,
    "parser_source_sha256": None,
    "parser_source_bytes": None,
    "probes": [],
}

try:
    with urllib.request.urlopen(base, timeout=10) as response:
        source_bytes = response.read()
    source = source_bytes.decode("utf-8")
    report["parser_source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    report["parser_source_bytes"] = len(source_bytes)
    module = types.ModuleType("deloox_branch_probe")
    module.__file__ = f"/embedded/{sha}/backend/scrapers/deloox/scraper.py"
    exec(compile(source, module.__file__, "exec"), module.__dict__)
except Exception as exc:
    report["fatal_error"] = "parser_source_load_failed: " + type(exc).__name__ + ": " + str(exc)[:240]
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0)

targets = [
    ("https://www.deloox.com/product/1380881/chloe-le-parfum-parfum-150-ml.html", "Chloe Le Parfum"),
    ("https://www.deloox.be/produit/1009926/hermes-eau-de-pamplemousse-rose-eau-de-cologne-100-ml.html", "Hermes Eau de Pamplemousse Rose"),
    ("https://www.deloox.be/produit/1321602/armani-acqua-di-gio-profondo-eau-de-parfum-30-ml.html", "Acqua di Gio Profondo"),
    ("https://www.deloox.be/produit/1323846/armani-acqua-di-gio-profondo-eau-de-parfum-100-ml.html", "Acqua di Gio Profondo"),
]
session = requests.Session()
session.headers.update(module.HEADERS)
for url, query in targets:
    row = {"url": url, "query": query}
    try:
        response = session.get(url, timeout=(3, 7), allow_redirects=True)
        row.update({
            "http_status": response.status_code,
            "final_url": response.url,
            "bytes": len(response.content),
            "content_type": response.headers.get("content-type"),
            "content_sha256": hashlib.sha256(response.content).hexdigest(),
        })
        if response.ok:
            parsed = module._product(response.url, response.text, query)
            row["parsed"] = bool(parsed)
            if parsed:
                row.update({
                    "name": parsed.get("name"),
                    "brand": (parsed.get("source") or {}).get("source_brand"),
                    "size_ml": ((parsed.get("attributes") or {}).get("size_ml") or {}).get("value"),
                    "concentration": ((parsed.get("attributes") or {}).get("concentration") or {}).get("value"),
                    "price": ((parsed.get("offer") or {}).get("price")),
                    "currency": ((parsed.get("offer") or {}).get("currency")),
                    "availability": ((parsed.get("offer") or {}).get("availability")),
                    "image": (parsed.get("source") or {}).get("image"),
                    "gtin": ((parsed.get("identity") or {}).get("gtin") or {}).get("value") if isinstance((parsed.get("identity") or {}).get("gtin"), dict) else None,
                    "sku": ((parsed.get("identity") or {}).get("sku") or {}).get("value") if isinstance((parsed.get("identity") or {}).get("sku"), dict) else None,
                })
            else:
                soup = module.BeautifulSoup(response.text, "html.parser")
                h1 = soup.find("h1")
                data = module._jsonld(soup)
                name = str(data.get("name") or (h1.get_text(" ", strip=True) if h1 else ""))
                row.update({
                    "parse_rejection": {
                        "name_found": bool(name),
                        "query_matches": bool(name and module.matches(name, query)),
                        "slug_matches": bool(name and module._url_matches_product_name(response.url, name)),
                        "jsonld_type": data.get("@type"),
                        "jsonld_name": data.get("name"),
                        "h1": h1.get_text(" ", strip=True)[:180] if h1 else None,
                        "title": soup.title.get_text(" ", strip=True)[:180] if soup.title else None,
                        "price_jsonld": (data.get("offers") or {}).get("price") if isinstance(data.get("offers"), dict) else None,
                        "gtin": data.get("gtin13") or data.get("gtin"),
                        "sku": data.get("sku"),
                        "jsonld_top_level_keys": sorted(data.keys()),
                    }
                })
        else:
            row["error"] = "non_success_http_status"
            row["body_prefix"] = response.text[:120].replace("\\n", " ")
    except Exception as exc:
        row["error"] = type(exc).__name__ + ": " + str(exc)[:240]
    report["probes"].append(row)
session.close()
report["probe_count"] = len(report["probes"])
report["http_success_count"] = sum(1 for p in report["probes"] if 200 <= p.get("http_status", 0) < 300)
report["parsed_count"] = sum(1 for p in report["probes"] if p.get("parsed") is True)
report["all_probes_completed"] = report["probe_count"] == len(targets)
report["result"] = "PASS" if report["all_probes_completed"] and report["parsed_count"] == len(targets) else "INCOMPLETE_OR_PARSE_FAILURE"
print(json.dumps(report, ensure_ascii=False, sort_keys=True))
