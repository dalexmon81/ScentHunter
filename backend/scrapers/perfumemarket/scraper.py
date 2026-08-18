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
 price_value=None;brand=None;data={}
 for sc in soup.select('script[type="application/ld+json"]'):
  try:d=json.loads(sc.get_text(strip=True))
  except Exception:continue
  stack=d if isinstance(d,list) else [d]
  while stack:
   x=stack.pop(0)
   if isinstance(x,list):stack.extend(x);continue
   if not isinstance(x,dict):continue
   if x.get("@type")=="Product" or "offers" in x:
    data=x;brand=x.get("brand");brand=brand.get("name") if isinstance(brand,dict) else brand
    offers=x.get("offers");offers=offers if isinstance(offers,list) else [offers]
    for o in offers:
     if isinstance(o,dict):
      price_value=price(o.get("price"))
      if price_value is not None:break
   if price_value is not None:break
 if price_value is None:price_value=price(soup.get_text(" ",strip=True))
 if price_value is None:return None
 text=norm(soup.get_text(" ",strip=True))
 stock="out_of_stock" if any(x in text for x in ("out of stock","uitverkocht","niet beschikbaar")) else ("in_stock" if any(x in text for x in ("in stock","op voorraad","beschikbaar")) else "unknown")
 meta=soup.select_one('meta[property="og:image"]');image=urljoin(url,meta.get("content","")) if meta else None
 return {"store":STORE,"source":{"source_name":name,"source_brand":clean(brand),"url":url,"image":image},"identity":{"gtin":None,"mpn":None,"sku":None,"store_product_id":None,"store_variant_id":None},"attributes":{"size_ml":{"value":size_ml(name),"source":"product_title"} if size_ml(name) is not None else None,"concentration":{"value":concentration(name),"source":"product_title"} if concentration(name) else None,"gender":{"value":"unknown","source":"not_explicit"},"packaging_type":{"value":"product","source":"default"}},"offer":{"price":round(price_value,2),"currency":"EUR","availability":stock},"provenance":{"source_page":url,"name_source":"h1","price_source":"jsonld_or_page"},"raw_data":{"jsonld":data},"name":name,"price":f"{price_value:.2f}".replace(".",",")+" €","url":url,"available":stock=="in_stock"}
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
