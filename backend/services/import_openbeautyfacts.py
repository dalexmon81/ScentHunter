import json
import urllib.parse
import urllib.request
from pathlib import Path

CATALOG_FILE = Path(__file__).resolve().parent.parent / "database" / "perfumes.json"
SEARCH_URL = "https://world.openbeautyfacts.org/cgi/search.pl"

def _get_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ScentHunter/0.1 - perfume catalog"}
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))

def search_open_beauty_facts(brand, name, page_size=20):
    params = {
        "search_terms": f"{brand} {name}",
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": page_size
    }
    data = _get_json(SEARCH_URL + "?" + urllib.parse.urlencode(params))
    return data.get("products", [])

def _norm(value):
    return " ".join(str(value or "").casefold().split())

def _score(product, brand, name):
    wanted_brand = _norm(brand)
    wanted_name = _norm(name)
    p_brand = _norm(product.get("brands"))
    p_name = _norm(product.get("product_name") or product.get("product_name_en"))

    score = 0
    if wanted_brand and wanted_brand in p_brand:
        score += 4
    if wanted_name and wanted_name == p_name:
        score += 6
    elif wanted_name and wanted_name in p_name:
        score += 4
    elif p_name and p_name in wanted_name:
        score += 2
    return score

def find_candidates(brand, name):
    products = search_open_beauty_facts(brand, name)
    candidates = []

    for product in products:
        image = (
            product.get("image_front_url")
            or product.get("image_url")
            or product.get("image_front_small_url")
        )
        if not image:
            continue

        score = _score(product, brand, name)
        if score < 4:
            continue

        code = str(product.get("code") or "")
        candidates.append({
            "brand": brand,
            "name": name,
            "image": image,
            "image_source": "Open Beauty Facts",
            "image_author": "Open Beauty Facts contributors",
            "image_license": "CC BY-SA",
            "image_source_page": (
                f"https://world.openbeautyfacts.org/product/{code}" if code else ""
            ),
            "barcode": code,
            "image_status": "pending",
            "match_score": score
        })

    candidates.sort(key=lambda x: x["match_score"], reverse=True)
    return candidates

def load_catalog():
    try:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"perfumes": []}
        data.setdefault("perfumes", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"perfumes": []}

def save_catalog(data):
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def add_candidate(candidate):
    data = load_catalog()
    key = (
        _norm(candidate.get("brand")),
        _norm(candidate.get("name")),
        candidate.get("image_source_page", "")
    )

    for old in data["perfumes"]:
        old_key = (
            _norm(old.get("brand")),
            _norm(old.get("name")),
            old.get("image_source_page", "")
        )
        if old_key == key:
            return False

    data["perfumes"].append(candidate)
    save_catalog(data)
    return True

def import_perfume(brand, name):
    candidates = find_candidates(brand, name)
    added = 0

    for candidate in candidates:
        if add_candidate(candidate):
            added += 1

    return {
        "brand": brand,
        "name": name,
        "found": len(candidates),
        "added": added,
        "status": "pending_review"
    }

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Uso: python backend/services/import_openbeautyfacts.py BRAND PROFUMO")
        raise SystemExit(1)

    result = import_perfume(sys.argv[1], " ".join(sys.argv[2:]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
