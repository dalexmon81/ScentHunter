"""Generic Deloox adapter for ScentHunter.

Uses Deloox search/category discovery and product pages only to collect RAW
offers. Product identity is resolved centrally by product_matcher.
"""
from __future__ import annotations
import json,re
from urllib.parse import quote_plus,urljoin
import requests
from bs4 import BeautifulSoup

STORE="Deloox"; BASE_URL="https://www.deloox.com"; TIMEOUT=10
HEADERS={"User-Agent":"Mozilla/5.0","Accept-Language":"en-GB,en;q=0.9"}

def clean(v):return re.sub(r"\s+"," ",str(v or "")).strip()
def norm(v):return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",clean(v).lower())).strip()
def tokens(v):return {x for x in norm(v).split() if len(x)>1}
def matches(text,q):
    q=tokens(q);return bool(q) and q.issubset(tokens(text))

def size_ml(*values):
    m=re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b"," ".join(clean(x) for x in values),re.I)
    if not m:return None
    n=float(m.group(1).replace(",","."));n*=10 if m.group(2).lower()=="cl" else 1
    return int(n) if n.is_integer() else n

def concentration(*values):
    t=norm(" ".join(clean(x) for x in values))
    if re.search(r"\beau de toilette\b|\bedt\b",t):return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b",t):return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b",t):return "Extrait de Parfum"
    return None

def parse_price(v):
    s=clean(v)
    m=re.search(r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?",s)
    if not m:return None
    try:return round(float(m.group(1).replace(",",".")),2)
    except ValueError:return None

def availability(text):
    t=norm(text)
    if any(x in t for x in ("sold out","out of stock","not available","currently unavailable")):return "out_of_stock"
    if any(x in t for x in ("in stock","available","op voorraad")):return "in_stock"
    return "unknown"

def _jsonld(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:data=json.loads(script.get_text(strip=True))
        except Exception:continue
        stack=data if isinstance(data,list) else [data]
        while stack:
            x=stack.pop(0)
            if isinstance(x,list):stack.extend(x);continue
            if not isinstance(x,dict):continue
            if x.get("@type")=="Product" or "offers" in x:return x
            if isinstance(x.get("@graph"),list):stack.extend(x["@graph"])
    return {}

def _product(url,html,query):
    soup=BeautifulSoup(html,"html.parser");data=_jsonld(soup)
    h1=soup.find("h1")
    name=clean(data.get("name")) or (clean(h1.get_text(" ",strip=True)) if h1 else "")
    if not name or not matches(name,query):return None
    brand=data.get("brand")
    if isinstance(brand,dict):brand=brand.get("name")
    offers=data.get("offers");offers=offers if isinstance(offers,list) else [offers]
    offer=next((x for x in offers if isinstance(x,dict)),{})
    price=parse_price(offer.get("price"))
    if price is None:
        text=soup.get_text(" ",strip=True);price=parse_price(text)
    if price is None:return None
    gtin=clean(data.get("gtin13") or data.get("gtin") or "") or None
    mpn=clean(data.get("mpn") or "") or None
    sku=clean(data.get("sku") or "") or None
    image=data.get("image")
    if isinstance(image,list):image=image[0] if image else None
    avail=availability(soup.get_text(" ",strip=True))
    return {
        "store":STORE,
        "source":{"source_name":name,"source_brand":clean(brand),"url":url,"image":urljoin(url,str(image)) if image else None},
        "identity":{
            "gtin":{"value":gtin,"source":"jsonld"} if gtin else None,
            "mpn":{"value":mpn,"source":"jsonld"} if mpn else None,
            "sku":{"value":sku,"source":"jsonld"} if sku else None,
            "store_product_id":{"value":sku,"source":"deloox_sku"} if sku else None,
        },
        "attributes":{
            "size_ml":{"value":size_ml(name),"source":"product_name"} if size_ml(name) is not None else None,
            "concentration":{"value":concentration(name),"source":"product_name"} if concentration(name) else None,
            "gender":{"value":"unknown","source":"not_explicit"},
            "packaging_type":{"value":"product","source":"default"},
        },
        "offer":{"price":price,"currency":"EUR","availability":avail},
        "provenance":{"source_page":url,"product_source":"jsonld_or_page"},
        "raw_data":{"jsonld":data},
        "name":name,"price":f"{price:.2f}".replace(".",",")+" €","url":url,"available":avail=="in_stock",
    }

def _discover(session,q):
    urls=[];seen=set()
    endpoints=[
        BASE_URL+"/en/search?query="+quote_plus(q),
        BASE_URL+"/en/search?search="+quote_plus(q),
        BASE_URL+"/en?search="+quote_plus(q),
    ]
    for endpoint in endpoints:
        try:r=session.get(endpoint,headers=HEADERS,timeout=TIMEOUT)
        except requests.RequestException:continue
        if r.status_code>=400:continue
        soup=BeautifulSoup(r.text,"html.parser")
        for a in soup.select('a[href*="/product/"]'):
            url=urljoin(BASE_URL,a.get("href","")).split("?")[0]
            text=clean(a.get_text(" ",strip=True))
            if url in seen:continue
            if matches(text+" "+url,q):
                seen.add(url);urls.append(url)
            if len(urls)>=20:return urls
    return urls

def search(query):
    query=clean(query)
    if not query:return []
    s=requests.Session();results=[];seen=set()
    try:
        for url in _discover(s,query):
            try:r=s.get(url,headers=HEADERS,timeout=TIMEOUT)
            except requests.RequestException:continue
            if r.status_code>=400:continue
            item=_product(url,r.text,query)
            if not item:continue
            key=(url,item["identity"].get("sku",{}).get("value") if item["identity"].get("sku") else None)
            if key not in seen:seen.add(key);results.append(item)
        return results
    finally:s.close()

def scrape(query):return search(query)

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("query");a=p.parse_args()
    print(json.dumps(search(a.query),ensure_ascii=False,indent=2))
