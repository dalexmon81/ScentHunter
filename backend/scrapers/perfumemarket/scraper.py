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
 loc=[x.get_text(strip=True) for x in BeautifulSoup(r.text,"html.parser").find_all("loc")]
 children=[u for u in loc if "sitemap" in u.lower() and u.lower().endswith(".xml")]
 if not children:return loc
 out=[]
 for u in children:
  try:
   rr=s.get(u,headers=HEADERS,timeout=TIMEOUT)
   if rr.status_code==200:out.extend(x.get_text(strip=True) for x in BeautifulSoup(rr.text,"html.parser").find_all("loc"))
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
 # Enriched output only; original discovery and validation are untouched.
 offers=data.get("offers"); offers=offers if isinstance(offers,list) else [offers]
 offer0=next((x for x in offers if isinstance(x,dict)),{})
 structured_price=price(offer0.get("price")) if offer0.get("price") is not None else None
 final_price=structured_price if structured_price is not None else price_value

 image=data.get("image")
 if isinstance(image,list): image=image[0] if image else None
 if isinstance(image,dict): image=image.get("url") or image.get("contentUrl")
 if not image:
  meta=soup.select_one('meta[property="og:image"]'); image=meta.get("content") if meta else None
 image=urljoin(url,str(image)) if image else None

 def _val(*keys):
  for key in keys:
   value=data.get(key)
   if isinstance(value,dict): value=value.get("name") or value.get("value") or value.get("@id")
   if value not in (None,""): return str(value).strip()
  return None

 gtin=_val("gtin","gtin13","gtin12","gtin14"); mpn=_val("mpn"); sku=_val("sku"); product_id=_val("productID","productId","product_id")
 availability=stock
 av=offer0.get("availability")
 if av:
  av=str(av).lower()
  if "outofstock" in av or "out of stock" in av: availability="out_of_stock"
  elif "instock" in av or "in stock" in av: availability="in_stock"
  elif "preorder" in av: availability="preorder"

 t=norm(name)
 gender="women" if re.search(r"\b(women|woman|dames|dame|femme|female)\b",t) else ("men" if re.search(r"\b(men|man|heren|homme|male)\b",t) else ("unisex" if "unisex" in t else "unknown"))
 size=size_ml(name); conc=concentration(name)

 return {
  "store":STORE,
  "source":{"source_name":name,"source_brand":clean(brand) or None,"url":url,"image":image},
  "identity":{"gtin":{"value":gtin,"source":"jsonld"} if gtin else None,"mpn":{"value":mpn,"source":"jsonld"} if mpn else None,"sku":{"value":sku,"source":"jsonld"} if sku else None,"store_product_id":{"value":product_id,"source":"jsonld"} if product_id else None,"store_variant_id":None},
  "attributes":{"size_ml":{"value":size,"source":"product_title"} if size is not None else None,"concentration":{"value":conc,"source":"product_title"} if conc else None,"gender":{"value":gender,"source":"product_title"},"packaging_type":{"value":"product","source":"default"}},
  "offer":{"price":round(final_price,2) if final_price is not None else None,"currency":"EUR","availability":availability},
  "provenance":{"source_page":url,"name_source":"h1","brand_source":"jsonld" if brand else None,"price_source":"jsonld" if structured_price is not None else "original_parser","product_source":"jsonld" if data else "product_page","availability_source":"jsonld" if av else "page_text"},
  "raw_data":{"jsonld":data},
  "name":name,"price":f"{final_price:.2f}".replace(".",",")+" €" if final_price is not None else None,"url":url,"available":availability=="in_stock"
 }
def search_page_urls(s,q):
 try:
  r=s.get(BASE+"/nl/search",params={"q":q},headers=HEADERS,timeout=TIMEOUT)
 except requests.RequestException:
  return []
 if r.status_code!=200:return []
 soup=BeautifulSoup(r.text,"html.parser")
 out=[];seen=set()
 for a in soup.select('a[href*="/products/"]'):
  href=a.get("href")
  if not href:continue
  u=urljoin(BASE,href.split("?")[0].split("#")[0])
  if u in seen:continue
  label=clean(a.get_text(" ",strip=True))
  if matches(label,q) or matches(u,q):
   seen.add(u);out.append(u)
 return out

def search(q):
 q=clean(q)
 if not q:return []
 s=requests.Session()
 try:
  out=[];seen=set()
  candidates=search_page_urls(s,q)
  if not candidates:
   candidates=[u for u in sitemap(s) if matches(u,q)][:50]
  for u in candidates[:50]:
   x=product(s,u,q)
   if x and x["url"] not in seen:
    seen.add(x["url"]);out.append(x)
  return out
 finally:s.close()
def scrape(q):return search(q)
if __name__=="__main__":
 import argparse
 p=argparse.ArgumentParser();p.add_argument("query");a=p.parse_args()
 print(json.dumps(search(a.query),ensure_ascii=False,indent=2))
