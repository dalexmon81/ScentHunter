"""Read-only live Deloox parser probe executed inside the Fly app network."""
import importlib.util
import json
import sys
import types
import urllib.request

import requests

sha = sys.argv[1]
base = f"https://raw.githubusercontent.com/dalexmon81/ScentHunter/{sha}/backend/scrapers/deloox/scraper.py"
with urllib.request.urlopen(base, timeout=15) as response:
    source = response.read().decode("utf-8")

module = types.ModuleType("deloox_branch_probe")
module.__file__ = f"/embedded/{sha}/backend/scrapers/deloox/scraper.py"
exec(compile(source, module.__file__, "exec"), module.__dict__)

targets = [
    ("https://www.deloox.com/product/1380881/chloe-le-parfum-parfum-150-ml.html", "Chloe Le Parfum"),
    ("https://www.deloox.be/produit/1009926/hermes-eau-de-pamplemousse-rose-eau-de-cologne-100-ml.html", "Hermes Eau de Pamplemousse Rose"),
    ("https://www.deloox.be/produit/1321602/armani-acqua-di-gio-profondo-eau-de-parfum-30-ml.html", "Acqua di Gio Profondo"),
    ("https://www.deloox.be/produit/1323846/armani-acqua-di-gio-profondo-eau-de-parfum-100-ml.html", "Acqua di Gio Profondo"),
]
session = requests.Session()
session.headers.update(module.HEADERS)
report = {
    "branch_sha": sha,
    "parser_source_sha256": __import__("hashlib").sha256(source.encode("utf-8")).hexdigest(),
    "read_only": True,
    "database_mutated": False,
    "probes": [],
}
for url, query in targets:
    row = {"url": url, "query": query}
    try:
        response = session.get(url, timeout=(5, 15), allow_redirects=True)
        row.update({"http_status": response.status_code, "final_url": response.url, "bytes": len(response.content)})
        if response.ok:
            parsed = module._product(response.url, response.text, query)
            row["parsed"] = bool(parsed)
            if parsed:
                row.update({
                    "name": parsed.get("name"),
                    "brand": (parsed.get("source") or {}).get("source_brand"),
                    "size_ml": ((parsed.get("attributes") or {}).get("size_ml") or {}).get("value"),
                    "price": ((parsed.get("offer") or {}).get("price")),
                    "availability": ((parsed.get("offer") or {}).get("availability")),
                })
        else:
            row["error"] = "non_success_http_status"
    except Exception as exc:
        row["error"] = type(exc).__name__ + ": " + str(exc)[:240]
    report["probes"].append(row)
session.close()
print(json.dumps(report, ensure_ascii=False, sort_keys=True))
