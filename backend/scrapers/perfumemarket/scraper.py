import json,re,unicodedata,requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
STORE="PerfumeMarket";BASE="https://www.perfumemarket.nl";SITEMAP=BASE+"/sitemap.xml";TIMEOUT=8
HEADERS={"User-Agent":"Mozilla/5.0","Accept-Language":"nl-NL,nl;q=0.9,en;q=0.8"}
def clean(v):return re.sub(r"\s+"," ",str(v or "")).strip()
def norm(v):
 x=unicodedata.normalize("NFKD",clean(v).lower());x="".join(c for c in x if not unicodedata.combining(c));return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",x)).strip()
def toks(v):return [x for x in norm(v).split() if len(x)>1]
def matches(t,q):return bool(set(toks(q))) and set(toks(q)).issubset(set(toks(t)))
def size_ml(v):
 m=re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",clean(v),re.I)
 if not m:return None
 n=float(m.group(1).replace(",","."));n*=10 if m.group(2).lower()=="cl" else 1;return int(n) if n.is_integer() else n
def concentration(v):
 t=norm(v)
 if re.search(r"\beau de toilette\b|\bedt\b",t):return "Eau de Toilette"
 if re.search(r"\beau de parfum\b|\bedp\b",t):return "Eau de Parfum"
 if re.search(r"\bextrait(?: de parfum)?\b",t):return "Extrait de Parfum"
 return None
def price(v):
 t=clean(v)
 if re.fullmatch(r"\d+(?:[.,]\d{1,2})?",t):return float(t.replace(",","."))
 m=re.search(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))\s*€",t)
 return float(m.group(1).replace(",",".")) if m else None
def sitemap(s):
 try:r=s.get(SITEMAP,headers=HEADERS,timeout=TIMEOUT)
 except requests.RequestException:return []
 if r.status_code!=200:return []
 loc=[x.get_text(strip=True) for x in BeautifulSoup(r.text,"xml").find_all("loc")]
 children=[u for u in loc if "sitemap" in u.lower() and u.lower().endswith(".xml")]
 if not children:return loc
 out=[]
 for u in children:
  try:
   rr=s.get(u,headers=HEADERS,timeout=TIMEOUT)
   if rr.status_code==200:out.extend(x.get_text(strip=True) for x in BeautifulSoup(rr.text,"xml").find_all("loc"))
  except requests.RequestException:pass
 return out
def product(s,url,q):
 try:r=s.get(url,headers=HEADERS,timeout=TIMEOUT)
 except requests.RequestException:return None
 if r.status_code!=200:return None
 soup=BeautifulSoup(r.text,"html.parser");h=soup.find("h1");name=clean(h.get_text(" ",strip=True)) if h else ""
 if not name or not matches(name,q):return None

 price_value=None;brand=None;data={};image=None
 gtin=None;mpn=None;sku=None;product_id=None;variant_id=None
 availability=None

 def first_value(v):
  if isinstance(v,dict):
   for k in ("name","value","id"):
    if v.get(k):return clean(v.get(k))
   return None
  return clean(v) if v not in (None,"") else None

 def walk_json(obj):
  nonlocal price_value,brand,data,image,gtin,mpn,sku,product_id,variant_id,availability
  if isinstance(obj,list):
   for item in obj: walk_json(item)
   return
  if not isinstance(obj,dict): return

  typ=obj.get("@type")
  types=typ if isinstance(typ,list) else [typ]
  is_product=any(isinstance(t,str) and t.lower() in ("product","productgroup") for t in types)

  if is_product or "offers" in obj:
   if is_product and not data:data=obj
   b=first_value(obj.get("brand"))
   if b and not brand:brand=b
   for key in ("gtin","gtin8","gtin12","gtin13","gtin14"):
    if obj.get(key) and not gtin:
     gtin=first_value(obj.get(key))
   if obj.get("mpn") and not mpn:mpn=first_value(obj.get("mpn"))
   if obj.get("sku") and not sku:sku=first_value(obj.get("sku"))
   if obj.get("productID") and not product_id:product_id=first_value(obj.get("productID"))
   if obj.get("image") and not image:
    im=obj.get("image")
    if isinstance(im,list):im=im[0] if im else None
    if isinstance(im,dict):im=im.get("url")
    if im:image=urljoin(url,clean(im))
   offers=obj.get("offers")
   offers=offers if isinstance(offers,list) else [offers]
   for o in offers:
    if not isinstance(o,dict):continue
    if price_value is None:
     price_value=price(o.get("price"))
    if not availability and o.get("availability"):
     availability=clean(o.get("availability")).rsplit("/",1)[-1].lower()
    if not variant_id and o.get("sku") and sku and clean(o.get("sku"))!=sku:
     variant_id=clean(o.get("sku"))
    for key in ("url","itemOffered"):
     item=o.get(key)
     if isinstance(item,dict):
      if not variant_id and item.get("sku"):variant_id=clean(item.get("sku"))
      if not product_id and item.get("productID"):product_id=clean(item.get("productID"))

  for key in ("@graph","mainEntity","mainEntityOfPage","itemOffered"):
   if key in obj:
    walk_json(obj[key])

 for sc in soup.select('script[type="application/ld+json"]'):
  try:d=json.loads(sc.get_text(strip=True))
  except Exception:continue
  walk_json(d)

 def meta_value(*selectors):
  for selector in selectors:
   tag=soup.select_one(selector)
   if tag:
    v=tag.get("content") or tag.get("value") or tag.get_text(" ",strip=True)
    if clean(v):return clean(v)
  return None

 image=image or meta_value('meta[property="og:image"]','meta[name="twitter:image"]','meta[itemprop="image"]')
 brand=brand or meta_value('meta[property="product:brand"]','meta[itemprop="brand"]')
 gtin=gtin or meta_value('meta[itemprop="gtin"]','meta[itemprop="gtin13"]','meta[itemprop="gtin12"]','meta[itemprop="gtin14"]','meta[itemprop="gtin8"]')
 mpn=mpn or meta_value('meta[itemprop="mpn"]')
 sku=sku or meta_value('meta[itemprop="sku"]')
 product_id=product_id or meta_value('meta[itemprop="productID"]')

 if image:image=urljoin(url,image)

 if price_value is None:price_value=price(soup.get_text(" ",strip=True))
 if price_value is None:return None

 page_text=norm(soup.get_text(" ",strip=True))
 if availability in ("outofstock","out_of_stock","soldout","sold_out"):
  stock="out_of_stock"
 elif availability in ("instock","in_stock","available"):
  stock="in_stock"
 elif any(x in page_text for x in ("out of stock","uitverkocht","niet beschikbaar")):
  stock="out_of_stock"
 elif any(x in page_text for x in ("in stock","op voorraad","beschikbaar")):
  stock="in_stock"
 else:
  stock="unknown"

 if not sku:
  m=re.search(r'\b(?:sku|art(?:ikel)?(?:nummer)?|product\s*(?:code|id))\s*[:#-]?\s*([a-z0-9._/-]+)',page_text,re.I)
  if m:sku=clean(m.group(1))

 return {"store":STORE,
  "source":{"source_name":name,"source_brand":clean(brand),"url":url,"image":image},
  "identity":{"gtin":gtin,"mpn":mpn,"sku":sku,"store_product_id":product_id,"store_variant_id":variant_id},
  "attributes":{"size_ml":{"value":size_ml(name),"source":"product_title"} if size_ml(name) is not None else None,
                "concentration":{"value":concentration(name),"source":"product_title"} if concentration(name) else None,
                "gender":{"value":"unknown","source":"not_explicit"},
                "packaging_type":{"value":"product","source":"default"}},
  "offer":{"price":round(price_value,2),"currency":"EUR","availability":stock},
  "provenance":{"source_page":url,"name_source":"h1","price_source":"jsonld_or_page"},
  "raw_data":{"jsonld":data},
  "name":name,"price":f"{price_value:.2f}".replace(".",",")+" €","url":url,"available":stock=="in_stock"}
def search(q):
 q=clean(q)
 if not q:return []
 s=requests.Session()
 try:
  out=[];seen=set()
  for u in [u for u in sitemap(s) if matches(u,q)][:30]:
   x=product(s,u,q)
   if x and x["url"] not in seen:seen.add(x["url"]);out.append(x)
  return out
 finally:s.close()
def scrape(q):return search(q)
if __name__=="__main__":
 import argparse
 p=argparse.ArgumentParser();p.add_argument("query");a=p.parse_args()
 print(json.dumps(search(a.query),ensure_ascii=False,indent=2))

# ============================================================
# PERFUMEMARKET FORENSIC DIAGNOSTIC
# Run directly: python scraper.py --diagnostic "Liquid brun"
# This diagnostic is bounded: it stops after the configured probes
# and prints a final machine-readable diagnosis.
# ============================================================

DIAG_TIMEOUT = 12
DIAG_MAX_CANDIDATES = 12

def _diag_log(msg):
    print("PERFUMEMARKET_FORENSIC: " + msg, flush=True)

def _diag_tokens(q):
    return [x for x in norm(q).split() if x]

def _diag_score(name, q):
    nt = norm(name)
    toks = _diag_tokens(q)
    if not toks:
        return 0.0
    return round(sum(1 for t in toks if t in nt) / len(toks), 3)

def _diag_fetch(s, label, url):
    started = time.time()
    _diag_log(f"HTTP_START label={label} method=GET url={url}")
    try:
        r = s.get(url, headers=HEADERS, timeout=DIAG_TIMEOUT, allow_redirects=True)
        elapsed = time.time() - started
        ct = r.headers.get("content-type", "")
        _diag_log(
            f"HTTP_END label={label} status={r.status_code} "
            f"elapsed={elapsed:.3f}s final={r.url} bytes={len(r.content)} type={ct!r}"
        )
        return r
    except Exception as e:
        elapsed = time.time() - started
        _diag_log(f"HTTP_ERROR label={label} elapsed={elapsed:.3f}s error={type(e).__name__}: {e}")
        return None

def forensic_diagnostic(query="Liquid brun"):
    q = clean(query)
    _diag_log("=" * 78)
    _diag_log(f"START query={q!r}")
    _diag_log(f"TOKENS={_diag_tokens(q)}")
    _diag_log(f"TIMEOUT={DIAG_TIMEOUT}s MAX_CANDIDATES={DIAG_MAX_CANDIDATES}")

    s = requests.Session()
    s.headers.update(HEADERS)

    base = "https://www.perfumemarket.nl"
    probes = [
        ("HOME", base + "/"),
        ("SEARCH_1", base + "/search?q=" + requests.utils.quote(q)),
        ("SEARCH_2", base + "/search?query=" + requests.utils.quote(q)),
        ("SEARCH_3", base + "/products.json?limit=12&query=" + requests.utils.quote(q)),
    ]

    evidence = {
        "home_ok": False,
        "search_http_ok": False,
        "query_seen": False,
        "candidates": [],
        "jsonld_products": 0,
        "product_candidates": 0,
        "matching_candidates": 0,
        "price_candidates": 0,
        "diagnosis": []
    }

    pages = []
    for label, url in probes:
        r = _diag_fetch(s, label, url)
        if not r:
            continue
        if label == "HOME":
            evidence["home_ok"] = r.status_code == 200
        if "SEARCH" in label and r.status_code == 200:
            evidence["search_http_ok"] = True
        if r.status_code != 200:
            continue
        body = r.text
        if norm(q) in norm(body):
            evidence["query_seen"] = True
        pages.append((label, r.url, body))

        soup = BeautifulSoup(body, "html.parser")

        # Product/JSON-LD evidence.
        for sc in soup.select('script[type="application/ld+json"]'):
            try:
                obj = json.loads(sc.get_text(strip=True))
            except Exception:
                continue
            stack = obj if isinstance(obj, list) else [obj]
            while stack:
                x = stack.pop(0)
                if isinstance(x, list):
                    stack.extend(x)
                elif isinstance(x, dict):
                    typ = x.get("@type")
                    types = typ if isinstance(typ, list) else [typ]
                    if any(str(t).lower() == "product" for t in types):
                        evidence["jsonld_products"] += 1

        # Candidate anchors: only product-looking URLs, bounded.
        seen = set()
        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a.get("href"))
            title = clean(a.get_text(" ", strip=True))
            if not href.startswith(base):
                continue
            if "/products/" not in href:
                continue
            key = (href, title)
            if key in seen:
                continue
            seen.add(key)
            score = _diag_score(title, q)
            evidence["candidates"].append({
                "url": href,
                "name": title,
                "score": score,
                "probe": label
            })

    # Deduplicate and retain only the strongest finite set.
    unique = {}
    for c in evidence["candidates"]:
        key = c["url"]
        if key not in unique or c["score"] > unique[key]["score"]:
            unique[key] = c
    candidates = sorted(unique.values(), key=lambda x: (-x["score"], x["url"]))[:DIAG_MAX_CANDIDATES]
    evidence["candidates"] = candidates
    evidence["product_candidates"] = len(candidates)

    for i, c in enumerate(candidates, 1):
        if c["score"] <= 0:
            continue
        evidence["matching_candidates"] += 1
        _diag_log(
            f"CANDIDATE_{i} score={c['score']:.3f} "
            f"url={c['url']} name={c['name']!r}"
        )

        r = _diag_fetch(s, f"PRODUCT_{i}", c["url"])
        if not r or r.status_code != 200:
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        h1 = soup.find("h1")
        pname = clean(h1.get_text(" ", strip=True)) if h1 else c["name"]
        pprice = None
        pimage = None
        pbrand = None
        pgtin = None
        pmpn = None
        psku = None

        meta_img = soup.select_one('meta[property="og:image"]')
        if meta_img and meta_img.get("content"):
            pimage = urljoin(r.url, meta_img["content"])

        for sc in soup.select('script[type="application/ld+json"]'):
            try:
                obj = json.loads(sc.get_text(strip=True))
            except Exception:
                continue
            stack = obj if isinstance(obj, list) else [obj]
            while stack:
                x = stack.pop(0)
                if isinstance(x, list):
                    stack.extend(x)
                    continue
                if not isinstance(x, dict):
                    continue
                typ = x.get("@type")
                types = typ if isinstance(typ, list) else [typ]
                if any(str(t).lower() == "product" for t in types):
                    b = x.get("brand")
                    pbrand = pbrand or (b.get("name") if isinstance(b, dict) else clean(b))
                    pgtin = pgtin or clean(x.get("gtin") or x.get("gtin13") or x.get("gtin12") or x.get("gtin14") or x.get("gtin8"))
                    pmpn = pmpn or clean(x.get("mpn"))
                    psku = psku or clean(x.get("sku"))
                    im = x.get("image")
                    if not pimage and im:
                        if isinstance(im, list):
                            im = im[0] if im else None
                        if isinstance(im, dict):
                            im = im.get("url")
                        if im:
                            pimage = urljoin(r.url, clean(im))
                    offers = x.get("offers")
                    offers = offers if isinstance(offers, list) else [offers]
                    for o in offers:
                        if isinstance(o, dict) and pprice is None:
                            pprice = price(o.get("price"))

        if pprice is None:
            pprice = price(soup.get_text(" ", strip=True))

        if pprice is not None:
            evidence["price_candidates"] += 1

        _diag_log(
            f"PRODUCT_{i}_EVIDENCE name={pname!r} "
            f"match={_diag_score(pname, q):.3f} price={pprice!r} "
            f"image={'yes' if pimage else 'no'} brand={pbrand!r} "
            f"gtin={pgtin!r} mpn={pmpn!r} sku={psku!r}"
        )

    # Final diagnosis: one conclusion, based only on observed evidence.
    if not evidence["home_ok"]:
        evidence["diagnosis"].append("SITE_HOME_UNREACHABLE_OR_NON_200")
    if not evidence["search_http_ok"]:
        evidence["diagnosis"].append("NATIVE_SEARCH_NOT_CONFIRMED")
    if evidence["search_http_ok"] and not evidence["query_seen"]:
        evidence["diagnosis"].append("SEARCH_RESPONSE_DOES_NOT_CONTAIN_QUERY")
    if evidence["product_candidates"] == 0:
        evidence["diagnosis"].append("NO_PRODUCT_CANDIDATE_DISCOVERED")
    elif evidence["matching_candidates"] == 0:
        evidence["diagnosis"].append("CANDIDATES_FOUND_BUT_NONE_MATCH_QUERY")
    elif evidence["price_candidates"] == 0:
        evidence["diagnosis"].append("MATCHING_PRODUCT_FOUND_BUT_NO_PRICE")
    else:
        evidence["diagnosis"].append("DISCOVERY_AND_PRODUCT_RETRIEVAL_WORK")

    _diag_log("-" * 78)
    _diag_log("FINAL_DIAGNOSIS=" + " | ".join(evidence["diagnosis"]))
    _diag_log(
        "SUMMARY "
        f"home_ok={evidence['home_ok']} "
        f"search_http_ok={evidence['search_http_ok']} "
        f"query_seen={evidence['query_seen']} "
        f"candidates={evidence['product_candidates']} "
        f"matching={evidence['matching_candidates']} "
        f"priced={evidence['price_candidates']} "
        f"jsonld_products={evidence['jsonld_products']}"
    )
    _diag_log("=" * 78)
    return evidence

if __name__ == "__main__":
    import sys
    if "--diagnostic" in sys.argv:
        idx = sys.argv.index("--diagnostic")
        q = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "Liquid brun"
        forensic_diagnostic(q)
