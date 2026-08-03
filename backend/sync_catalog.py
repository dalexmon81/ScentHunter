#!/usr/bin/env python3
import json, re, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "scenthunter_catalog.json"
STATE = HERE / "catalog_sync_state.json"

BASE = "https://world.openbeautyfacts.org/api/v2/search"
FIELDS = "code,product_name,brands,categories_tags,image_front_url,image_url"
PAGE_SIZE = 100

def norm(v):
    v = str(v or "").lower().strip()
    v = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", v)
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()

def aliases(name, brand):
    vals = {norm(name), norm(f"{brand} {name}")}
    vals |= {x.replace(" ", "") for x in list(vals) if x}
    return sorted(x for x in vals if x)

def key(item):
    return norm(f"{item.get('brand','')}|{item.get('name','')}")

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def fetch_page(page):
    params = {
        "categories_tags_en": "perfumes",
        "page": page,
        "page_size": PAGE_SIZE,
        "fields": FIELDS,
        "sort_by": "nothing",
    }
    req = Request(
        BASE + "?" + urlencode(params),
        headers={"User-Agent": "ScentHunter/0.1 (catalog sync)"}
    )
    with urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    catalog = load_json(CATALOG, [])
    by_key = {key(x): x for x in catalog if isinstance(x, dict) and x.get("name")}
    state = load_json(STATE, {"next_page": 1})
    page = max(1, int(state.get("next_page", 1)))

    print(f"Starting at page {page}. Current catalog: {len(by_key)}")

    # One run = at most 10 pages / 1000 records. Run again to continue.
    for _ in range(10):
        try:
            payload = fetch_page(page)
        except (HTTPError, URLError, TimeoutError) as e:
            print("Stopped:", repr(e))
            break

        products = payload.get("products") or []
        if not products:
            print("No more products.")
            state["next_page"] = page
            save_json(STATE, state)
            break

        added = 0
        for p in products:
            name = str(p.get("product_name") or "").strip()
            brand = str(p.get("brands") or "").split(",")[0].strip()
            if not name:
                continue
            item = {
                "catalog_id": p.get("code"),
                "name": name,
                "brand": brand,
                "image": p.get("image_front_url") or p.get("image_url") or "",
                "aliases": aliases(name, brand),
                "source": "open-beauty-facts",
                "source_url": f"https://world.openbeautyfacts.org/product/{p.get('code')}" if p.get("code") else "",
                "data_license": "ODbL",
                "image_license": "CC BY-SA",
            }
            k = key(item)
            if k not in by_key:
                by_key[k] = item
                added += 1
            else:
                old = by_key[k]
                if not old.get("image") and item["image"]:
                    old["image"] = item["image"]
                    old["image_source"] = "open-beauty-facts"
                    old["image_license"] = "CC BY-SA"
                old["aliases"] = sorted(set(old.get("aliases", [])) | set(item["aliases"]))

        page += 1
        state["next_page"] = page
        save_json(STATE, state)
        save_json(CATALOG, sorted(by_key.values(), key=lambda x:(norm(x.get("brand")),norm(x.get("name")))))
        print(f"Page {page-1}: {len(products)} read, {added} added. Total {len(by_key)}")
        time.sleep(1)

        count = int(payload.get("count") or 0)
        if count and (page - 1) * PAGE_SIZE >= count:
            print("Catalog sync complete.")
            break

if __name__ == "__main__":
    main()
