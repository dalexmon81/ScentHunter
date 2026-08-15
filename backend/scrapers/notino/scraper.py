"""Generic Notino adapter for ScentHunter.

Discovery belongs here; product identity belongs to the central Identity Engine.
No product/brand-specific rules are used.
"""
from __future__ import annotations
import json, os, re
from urllib.parse import quote_plus, urljoin, urlparse
import requests
from bs4 import BeautifulSoup

STORE="Notino"
BASE_URL="https://www.notino.fr"
TIMEOUT=int(os.getenv("NOTINO_TIMEOUT","20"))
HEADERS={"User-Agent":"Mozilla/5.0","Accept-Language":"fr-FR,fr;q=0.9,en;q=0.8"}

def clean(v): return re.sub(r"\s+"," ",str(v or "")).strip()
def norm(v): return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",clean(v).lower())).strip()
def tokens(v): return {x for x in norm(v).split() if len(x)>1}
def matches(text,q):
    q=tokens(q); t=tokens(text)
    return bool(q) and q.issubset(t)

def size_ml(*values):
    m=re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b"," ".join(clean(x) for x in values),re.I)
    if not m:return None
    n=float(m.group(1).replace(",",".")); n*=10 if m.group(2).lower()=="cl" else 1
    return int(n) if n.is_integer() else n

def concentration(*values):
    t=norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b",t):return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b",t):return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b",t):return "Extrait de Parfum"
    return None

def parse_price(v):
    if v is None:return None
    s=clean(v).replace("\xa0"," ")
    m=re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)",s)
    if not m:return None
    raw=m.group(1)
    if "," in raw and "." in raw: raw=raw.replace(".","").replace(",",".")
    else: raw=raw.replace(",",".")
    try:return round(float(raw),2)
    except ValueError:return None

def availability(value):
    t=norm(value)
    if any(x in t for x in ("out of stock","outofstock","rupture de stock","indisponible","epuise","épuisé")):
        return "out_of_stock"
    if any(x in t for x in ("in stock","instock","en stock","disponible","available")):
        return "in_stock"
    return "unknown"

def _jsonld(soup):
    out=[]
    for script in soup.select('script[type="application/ld+json"]'):
        try:data=json.loads(script.get_text(strip=True))
        except Exception:continue
        stack=data if isinstance(data,list) else [data]
        while stack:
            x=stack.pop(0)
            if isinstance(x,list):stack.extend(x);continue
            if not isinstance(x,dict):continue
            if x.get("@type")=="Product" or "offers" in x:out.append(x)
            for key in ("@graph","mainEntity"):
                if isinstance(x.get(key),(dict,list)):stack.append(x[key])
    return out

def _jsonld_size_ml(product, offer):
    candidates=[]
    for obj in (offer, product):
        if not isinstance(obj,dict):
            continue
        for key in ("name","description","category"):
            value=obj.get(key)
            if value:
                candidates.append(clean(value))
    for value in candidates:
        size=size_ml(value)
        if size is not None:
            return size
    return None


def _raw(product,url):
    name=clean(product.get("name"))
    brand=product.get("brand")
    if isinstance(brand,dict):brand=brand.get("name")
    offers=product.get("offers")
    offers=offers if isinstance(offers,list) else [offers]
    offer=next((x for x in offers if isinstance(x,dict)),{})
    price=parse_price(offer.get("price"))
    avail=availability(offer.get("availability"))
    size=_jsonld_size_ml(product, offer)
    gtin=clean(product.get("gtin13") or product.get("gtin") or "") or None
    sku=clean(product.get("sku") or "") or None
    image=product.get("image")
    if isinstance(image,list):image=image[0] if image else None
    return {
        "store":STORE,
        "source":{"source_name":name,"source_brand":clean(brand),"url":url,"image":urljoin(url,str(image)) if image else None},
        "identity":{
            "gtin":{"value":gtin,"source":"jsonld"} if gtin else None,
            "mpn":{"value":clean(product.get("mpn")),"source":"jsonld"} if product.get("mpn") else None,
            "sku":{"value":sku,"source":"jsonld"} if sku else None,
            "store_product_id":{"value":sku,"source":"notino_sku"} if sku else None,
        },
        "attributes":{
            "size_ml":{"value":size,"source":"jsonld_offer_or_product"} if size is not None else None,
            "concentration":{"value":concentration(name),"source":"product_name"} if concentration(name) else None,
            "gender":{"value":"unknown","source":"not_explicit"},
            "packaging_type":{"value":"product","source":"default"},
        },
        "offer":{"price":price,"currency":"EUR","availability":avail},
        "provenance":{"source_page":url,"product_source":"jsonld"},
        "raw_data":{"jsonld":product},
        "name":name,"price":f"{price:.2f}".replace(".",",")+" €" if price is not None else "",
        "url":url,"available":avail=="in_stock",
    }

def _discover(session,q):
    urls=[]
    search=BASE_URL+"/search.asp?exps="+quote_plus(q)
    try:r=session.get(search,headers=HEADERS,timeout=TIMEOUT)
    except requests.RequestException:return []
    if r.status_code>=400:return []
    soup=BeautifulSoup(r.text,"html.parser")
    for a in soup.select("a[href]"):
        href=urljoin(BASE_URL,a.get("href","")).split("?")[0]
        if urlparse(href).netloc not in ("www.notino.fr","notino.fr"):continue
        text=clean(a.get_text(" ",strip=True))
        if "/product/" not in href.lower() and not matches(text,q):continue
        if matches(text+" "+href,q) and href not in urls:urls.append(href)
        if len(urls)>=20:break
    return urls

def search(query):
    query=clean(query)
    if not query:return []
    s=requests.Session(); results=[];seen=set()
    try:
        for url in _discover(s,query):
            try:r=s.get(url,headers=HEADERS,timeout=TIMEOUT)
            except requests.RequestException:continue
            if r.status_code>=400:continue
            soup=BeautifulSoup(r.text,"html.parser")
            for product in _jsonld(soup):
                name=clean(product.get("name"))
                if not name or not matches(name,query):continue
                item=_raw(product,url)
                key=(url,item["identity"].get("sku",{}).get("value") if item["identity"].get("sku") else None)
                if key not in seen:seen.add(key);results.append(item)
        return results
    finally:s.close()

def scrape(query):return search(query)

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("query");a=p.parse_args()
    print(json.dumps(search(a.query),ensure_ascii=False,indent=2))
