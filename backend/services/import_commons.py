import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

CATALOG_FILE = Path(__file__).resolve().parent.parent / "database" / "perfumes.json"
API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_LICENSE_PREFIXES = ("cc0", "public domain", "cc by ")

def _clean_html(value):
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ScentHunter/0.1"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

def search_commons(brand, name, limit=8):
    params = {
        "action": "query", "generator": "search",
        "gsrsearch": f"{brand} {name} perfume bottle",
        "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|extmetadata",
        "iiurlwidth": 600, "format": "json", "origin": "*"
    }
    data = _get(API + "?" + urllib.parse.urlencode(params))
    return list(data.get("query", {}).get("pages", {}).values())

def candidate_from_page(page):
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    license_name = _clean_html(meta.get("LicenseShortName", {}).get("value"))
    if not any(license_name.casefold().startswith(x) for x in ALLOWED_LICENSE_PREFIXES):
        return None
    image_url = info.get("thumburl") or info.get("url")
    if not image_url:
        return None
    return {
        "image": image_url,
        "image_source": "Wikimedia Commons",
        "image_author": _clean_html(meta.get("Artist", {}).get("value")),
        "image_license": license_name,
        "image_license_url": _clean_html(meta.get("LicenseUrl", {}).get("value")),
        "image_source_page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
            page.get("title", "").replace(" ", "_")
        ),
        "image_status": "pending"
    }

def find_legal_candidates(brand, name):
    result = []
    for page in search_commons(brand, name):
        item = candidate_from_page(page)
        if item:
            item["brand"] = brand
            item["name"] = name
            result.append(item)
    return result

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
    CATALOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def add_candidate(candidate):
    data = load_catalog()
    key = (candidate.get("brand","").casefold(), candidate.get("name","").casefold(),
           candidate.get("image_source_page",""))
    for old in data["perfumes"]:
        old_key = (str(old.get("brand","")).casefold(), str(old.get("name","")).casefold(),
                   old.get("image_source_page",""))
        if old_key == key:
            return False
    data["perfumes"].append(candidate)
    save_catalog(data)
    return True


def import_perfume(brand, name):
    """
    Cerca candidati con licenza consentita e li salva come pending.
    Nessuna immagine viene approvata automaticamente.
    """
    candidates = find_legal_candidates(brand, name)
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
        print("Uso: python backend/services/import_commons.py BRAND PROFUMO")
        raise SystemExit(1)

    brand = sys.argv[1]
    name = " ".join(sys.argv[2:])

    result = import_perfume(brand, name)
    print(json.dumps(result, ensure_ascii=False, indent=2))
