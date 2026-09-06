import json
import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

STOPWORDS = {
    "eau","de","parfum","perfume","edp","edt","extrait","spray","for","by","pour",
    "ml","cl","men","man","women","woman","male","female","homme","femme","herren","damen",
}

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()

def query_tokens(q):
    out=[]
    for token in norm(q).split():
        if token in STOPWORDS or re.fullmatch(r"\d+(?:[.,]\d+)?", token):
            continue
        out.append(token)
    return out

def matches(text, q):
    hay=set(norm(text).split())
    toks=query_tokens(q)
    return bool(toks) and all(t in hay for t in toks)

def size_ml(*values):
    m=re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", " ".join(clean(x) for x in values), re.I)
    if not m: return None
    n=float(m.group(1).replace(",", "."))
    if m.group(2).lower()=="cl": n*=10
    return int(n) if n.is_integer() else n

def concentration(*values):
    t=norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b", t): return "Eau de Toilette"
    if re.search(r"\bextrait(?: de parfum)?\b", t): return "Extrait de Parfum"
    if re.search(r"\beau de parfum\b|\bedp\b", t): return "Eau de Parfum"
    return None

def price(v):
    if v in (None,""): return None
    # Shopify product JSON normally exposes integer prices in cents.
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n=float(v)
        if n.is_integer() and abs(n) >= 100:
            n /= 100.0
        return round(n, 2)
    s=clean(v).replace("€","").strip()
    m=re.search(r"\d+(?:[.,]\d{1,2})?", s)
    if not m: return None
    raw=m.group(0)
    try:
        n=float(raw.replace(",","."))
        if re.fullmatch(r"\d+", raw) and n >= 100:
            n /= 100.0
        return round(n,2)
    except ValueError:
        return None

def _get(session,url,params=None):
    try:
        r=session.get(url,params=params,headers=HEADERS,timeout=TIMEOUT)
        return r if r.ok else None
    except requests.RequestException:
        return None

def _urls_from_sitemap(session, q, limit=80):
    urls=[]; seen=set()
    try:
        r=_get(session,BASE_URL+"/robots.txt")
        if not r: return []
        sitemaps=re.findall(r"(?im)^\s*sitemap:\s*(\S+)",r.text or "")
        queue=sitemaps[:10]
        while queue and len(urls)<limit:
            sm=queue.pop(0)
            x=_get(session,sm)
            if not x: continue
            soup=BeautifulSoup(x.text,"xml")
            locs=[u.get_text(strip=True) for u in soup.find_all("loc")]
            for u in locs:
                if u.endswith(".xml") or "sitemap" in u.lower():
                    if u not in queue and u not in seen: queue.append(u)
                elif "/products/" in u and matches(u,q):
                    u=u.split("?")[0].rstrip("/")
                    if u not in seen:
                        seen.add(u); urls.append(u)
                        if len(urls)>=limit: break
    except Exception:
        pass
    return urls

def _discover(session,q):
    urls=[]; seen=set()
    def add(u):
        if not u: return
        u=urljoin(BASE_URL,str(u)).split("?")[0].split("#")[0].rstrip("/")
        if "/products/" in u and u not in seen:
            seen.add(u); urls.append(u)
    search_queries=[q]
    toks=query_tokens(q)
    if toks:
        search_queries.append(" ".join(toks))
        for t in toks:
            search_queries.append(t)
    for sq in search_queries:
        r=_get(session,BASE_URL+"/search/suggest.json",{
            "q":sq,"resources[type]":"product","resources[limit]":50,
            "resources[options][unavailable_products]":"show"
        })
        if r:
            try:
                data=r.json()
                products=((data.get("resources") or {}).get("results") or {}).get("products") or []
                for p in products:
                    if isinstance(p,dict):
                        u=p.get("url") or p.get("product_url")
                        if matches(f"{p.get('title','')} {p.get('vendor','')} {u or ''}",q): add(u)
            except (ValueError,TypeError): pass
        r=_get(session,BASE_URL+"/search.json",{"q":sq,"type":"product","limit":50})
        if r:
            try:
                for p in r.json().get("products") or []:
                    if isinstance(p,dict):
                        u=p.get("url") or p.get("handle")
                        if u and not str(u).startswith("/products/") and p.get("handle"):
                            u="/products/"+p["handle"]
                        if matches(f"{p.get('title','')} {p.get('vendor','')} {u or ''}",q): add(u)
            except (ValueError,TypeError): pass
    r=_get(session,BASE_URL+"/search",{"q":q,"type":"product"})
    if r:
        soup=BeautifulSoup(r.text,"html.parser")
        for a in soup.select('a[href*="/products/"]'):
            u=a.get("href")
            text=f"{a.get('title','')} {a.get_text(' ',strip=True)} {u or ''}"
            if matches(text,q): add(u)
    # Last-resort catalog discovery. This is what protects against Shopify
    # search endpoints intermittently returning zero candidates.
    for u in _urls_from_sitemap(session,q):
        add(u)
    return urls[:80]

def _product_json(session,url):
    r=_get(session,url.rstrip("/")+".js")
    if not r: return None
    try:
        data=r.json()
        return data if isinstance(data,dict) else None
    except (ValueError,TypeError):
        return None

def _item(product,variant,url):
    name=clean(product.get("title"))
    vname=clean(variant.get("title"))
    source_name=name if not vname or vname=="Default Title" else f"{name} {vname}"
    if not matches(f"{name} {product.get('vendor','')} {url}", CURRENT_QUERY):
        return None
    p=price(variant.get("price"))
    if p is None: return None
    size=size_ml(vname,name)
    conc=concentration(vname,name)
    available=variant.get("available")
    if available is True: stock="in_stock"
    elif available is False: stock="out_of_stock"
    else: stock="unknown"
    image=product.get("featured_image")
    if isinstance(image,dict): image=image.get("src") or image.get("url")
    if not image:
        imgs=product.get("images") or []
        image=imgs[0] if imgs else None
    return {
        "store":STORE,
        "source":{"source_name":source_name,"source_brand":clean(product.get("vendor")) or None,"url":url,"image":urljoin(BASE_URL,str(image)) if image else None},
        "identity":{"gtin":None,"mpn":None,"sku":({"value":str(variant.get("sku")),"source":"shopify_variant"} if variant.get("sku") else None),
                    "store_product_id":({"value":product.get("id"),"source":"shopify_product"} if product.get("id") is not None else None),
                    "store_variant_id":({"value":variant.get("id"),"source":"shopify_variant"} if variant.get("id") is not None else None)},
        "attributes":{"size_ml":({"value":size,"source":"product_variant"} if size is not None else None),
                      "concentration":({"value":conc,"source":"product_title"} if conc else None),
                      "gender":{"value":"unknown","source":"not_explicit"},"packaging_type":{"value":"product","source":"default"}},
        "offer":{"price":p,"currency":"EUR","availability":stock},
        "provenance":{"source_page":url,"product_source":"shopify_product_json","variant_source":"shopify_product_json"},
        "raw_data":{"product":product,"variant":variant},
        "name":name,"price":f"{p:.2f}".replace(".",",")+" €","url":url,"available":available
    }

CURRENT_QUERY=""

def search(query):
    global CURRENT_QUERY
    CURRENT_QUERY=clean(query)
    if not CURRENT_QUERY: return []
    session=requests.Session()
    try:
        out=[]; seen=set()
        for url in _discover(session,CURRENT_QUERY):
            data=_product_json(session,url)
            if not data: continue
            variants=data.get("variants") or []
            for v in variants:
                if not isinstance(v,dict): continue
                item=_item(data,v,url)
                if not item: continue
                key=(item["url"],(item["identity"]["store_variant_id"] or {}).get("value"))
                if key in seen: continue
                seen.add(key); out.append(item)
        return out
    finally:
        session.close()

def scrape(query):
    return search(query)

def diagnose(query):
    global CURRENT_QUERY
    CURRENT_QUERY=clean(query)
    session=requests.Session()
    try:
        urls=_discover(session,CURRENT_QUERY)
        return {"diagnostic":True,"query":CURRENT_QUERY,"candidate_count":len(urls),"candidates":urls[:50]}
    finally:
        session.close()

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose",action="store_true")
    args=parser.parse_args()
    print(json.dumps(diagnose(args.query) if args.diagnose else search(args.query),ensure_ascii=False,indent=2))
