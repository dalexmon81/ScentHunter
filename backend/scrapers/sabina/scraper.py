import json,re
from urllib.parse import quote_plus,urljoin
import requests
from bs4 import BeautifulSoup
STORE="Sabina"; BASE="https://www.sabina.com"; TIMEOUT=6
HEADERS={"User-Agent":"Mozilla/5.0","Accept-Language":"it-IT,it;q=0.9,en;q=0.8"}
def clean(v): return re.sub(r"\s+"," ",str(v or "")).strip()
def norm(v): return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",clean(v).lower())).strip()
def toks(v): return [x for x in norm(v).split() if len(x)>1]
def matches(text,q): return bool(set(toks(q))) and set(toks(q)).issubset(set(toks(text)))
def size_ml(*vals):
    m=re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b"," ".join(clean(x) for x in vals),re.I)
    if not m:return None
    n=float(m.group(1).replace(",",".")); n*=10 if m.group(2).lower()=="cl" else 1
    return int(n) if n.is_integer() else n
def concentration(*vals):
    t=norm(" ".join(clean(x) for x in vals))
    if re.search(r"\beau de toilette\b|\bedt\b",t):return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b",t):return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b",t):return "Extrait de Parfum"
    return None
def parse_price(v):
    text=clean(v)
    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?",text):
        return float(text.replace(",","."))
    m=re.search(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{2}))\s*(?:€|EUR)|(?:€|EUR)\s*(\d{1,4}(?:[.,]\d{2}))",text,re.I)
    if not m:return None
    return float(next(x for x in m.groups() if x).replace(",","."))

def product_from_html(url,query,html):
    soup=BeautifulSoup(html,"html.parser"); h1=soup.find("h1")
    name=clean(h1.get_text(" ",strip=True)) if h1 else ""
    if not name or not matches(name,query): return None
    price=None
    for script in soup.select('script[type="application/ld+json"]'):
        try:data=json.loads(script.get_text(strip=True))
        except Exception:continue
        stack=data if isinstance(data,list) else [data]
        while stack:
            x=stack.pop(0)
            if isinstance(x,list):stack.extend(x);continue
            if not isinstance(x,dict):continue
            offers=x.get("offers"); offers=offers if isinstance(offers,list) else [offers]
            for offer in offers:
                if isinstance(offer,dict):
                    price=parse_price(offer.get("price"))
                    if price is not None:break
            if price is not None:break
    if price is None:price=parse_price(soup.get_text(" ",strip=True))
    if price is None:return None
    stock_text=norm(soup.get_text(" ",strip=True))
    stock="out_of_stock" if any(x in stock_text for x in ("out of stock","sold out","non disponibile","esaurito","rupture de stock","indisponible","ausverkauft")) else ("in_stock" if any(x in stock_text for x in ("in stock","disponibile","en stock","auf lager")) else "unknown")
    meta=soup.select_one('meta[property="og:image"]'); image=urljoin(url,meta.get("content","")) if meta else None
    return {"store":STORE,"source":{"source_name":name,"source_brand":None,"url":url,"image":image},
      "identity":{"gtin":None,"mpn":None,"sku":None,"store_product_id":None,"store_variant_id":None},
      "attributes":{"size_ml":{"value":size_ml(name),"source":"product_title"} if size_ml(name) is not None else None,
      "concentration":{"value":concentration(name),"source":"product_title"} if concentration(name) else None,
      "gender":{"value":"unknown","source":"not_explicit"},"packaging_type":{"value":"product","source":"default"}},
      "offer":{"price":round(price,2),"currency":"EUR","availability":stock},
      "provenance":{"source_page":url,"name_source":"h1","price_source":"jsonld_or_page"},"raw_data":{},
      "name":name,"price":f"{price:.2f}".replace(".",",")+" €","url":url,"available":stock=="in_stock"}

def search(query):
    query=clean(query)
    if not query:return []
    s=requests.Session()
    try:
        results=[];seen=set()
        for u in (BASE+"/it/ricerca?search_query="+quote_plus(query),BASE+"/it/ricerca_old?s="+quote_plus(query)):
            try:r=s.get(u,headers=HEADERS,timeout=TIMEOUT)
            except requests.RequestException:continue
            if r.status_code>=400:continue
            soup=BeautifulSoup(r.text,"html.parser")
            for a in soup.select("a[href]"):
                url=urljoin(BASE,a.get("href","")).split("?")[0]
                if url in seen or not matches(clean(a.get_text(" ",strip=True))+" "+url,query):continue
                seen.add(url)
                try:p=s.get(url,headers=HEADERS,timeout=TIMEOUT)
                except requests.RequestException:continue
                if p.status_code==200:
                    item=product_from_html(url,query,p.text)
                    if item:results.append(item)
                if len(results)>=20:return results
        return results
    finally:s.close()
def scrape(query):return search(query)
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("query");a=p.parse_args()
    print(json.dumps(search(a.query),ensure_ascii=False,indent=2))
