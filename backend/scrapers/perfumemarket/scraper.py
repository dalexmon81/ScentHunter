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
