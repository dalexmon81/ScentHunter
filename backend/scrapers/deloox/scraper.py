import json
import re
import unicodedata
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

STORE='Deloox'; BASE_URL='https://www.deloox.com'; HOME_URL=f'{BASE_URL}/en'; TIMEOUT=10
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36','Accept-Language':'en-GB,en;q=0.9'}
PRICE_RE=re.compile(r'(?:€\s*(\d{1,4})\s*[,.]\s*(\d{2})|(?<!\d)(\d{1,4})\s*[,.]\s*(\d{2})\s*€|€\s*(\d{1,4})(?![\d.,])|(\d{1,4})\s*€)',re.I)
SIZE_RE=re.compile(r'\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b',re.I); SIZE_FULL_RE=re.compile(r'^(\d{1,3}(?:[.,]\d+)?)\s*ml$',re.I)
SOLD_OUT=('sold out','out of stock','not available','currently unavailable')
NON_FRAGRANCE=('body mist','body spray','body lotion','body cream','body oil','body wash','shower gel','shower oil','hand and body','hand cream','deodorant','after shave','aftershave','hair mist','hair spray','soap')
CATEGORY_FALLBACKS=((("liquid","brun"),"https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html"),(("french","avenue"),"https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html"),(("le","beau","le","parfum"),"https://www.deloox.com/category/1084243/le-beau-le-parfum.html"),(("jean","paul","gaultier"),"https://www.deloox.com/category/1072906/jean-paul-gaultier-fragrances.html"),(("miu","miu"),"https://www.deloox.com/category/1071574/miu-miu-fragrances.html"))

def clean(v): return re.sub(r'\s+',' ',str(v or '')).strip()
def norm(v):
    v=unicodedata.normalize('NFKD',clean(v).lower()); v=''.join(c for c in v if not unicodedata.combining(c)); return re.sub(r'[^a-z0-9]+',' ',v).strip()
def tokens(v): return [x for x in norm(v).split() if len(x)>1]
def price(text):
    m=PRICE_RE.search(clean(text))
    if not m:return None
    if m.group(1):return f'{m.group(1)},{m.group(2)} €'
    if m.group(3):return f'{m.group(3)},{m.group(4)} €'
    if m.group(5):return f'{m.group(5)},00 €'
    if m.group(6):return f'{m.group(6)},00 €'

def get(session,url):
    try:
        r=session.get(url,headers=HEADERS,timeout=TIMEOUT,allow_redirects=True); r.raise_for_status(); return r
    except requests.RequestException as e:
        print(f'DELOOX ERROR: {e}'); return None

def relevant(text,query):
    q=set(tokens(query)); t=set(tokens(text))
    if not q or len(q&t)/len(q)<0.55:return False
    return not any(norm(x) in norm(text) for x in NON_FRAGRANCE)

def url_match(url,query):
    q=set(tokens(query)); u=set(tokens(url)); return bool(q) and q.issubset(u)

def find_category(session,query):
    q=set(tokens(query))
    for req,url in CATEGORY_FALLBACKS:
        if set(req).issubset(q): return url
    r=get(session,HOME_URL)
    if not r:return None
    soup=BeautifulSoup(r.text,'html.parser'); c=[]
    for a in soup.find_all('a',href=True):
        n=clean(a.get_text(' ',strip=True)); u=urljoin(BASE_URL,clean(a.get('href')))
        if '/category/' not in u.lower():continue
        ov=len(set(tokens(n))&q)
        if ov:c.append((ov,u))
    return max(c)[1] if c else None

def find_card(a):
    n=a
    for _ in range(8):
        if n is None:break
        t=clean(n.get_text(' ',strip=True))
        if price(t) or SIZE_RE.search(t):return n
        n=n.parent
    return a

def extract_candidates(html,query):
    soup=BeautifulSoup(html,'html.parser'); out=[]; seen=set(); q=set(tokens(query))
    for a in soup.find_all('a',href=True):
        u=urljoin(BASE_URL,clean(a.get('href'))).split('?')[0]
        if '/product/' not in u.lower() or not url_match(u,query):continue
        card=find_card(a); text=clean(card.get_text(' ',strip=True))
        if any(x in text.lower() for x in SOLD_OUT) or not relevant(text,query):continue
        p=price(text); title=clean(a.get('title') or a.get_text(' ',strip=True))
        if not p or not (q.issubset(set(tokens(title))) or q.issubset(set(tokens(text)))):continue
        if u in seen:continue
        seen.add(u); out.append({'name':title or query,'price':p,'url':u})
    return out

def page_names(html):
    soup=BeautifulSoup(html,'html.parser'); names=[]
    for h in soup.find_all('h1'):
        x=clean(h.get_text(' ',strip=True))
        if x:names.append(x)
    for s in soup.find_all('script',type='application/ld+json'):
        try:d=json.loads(s.string or s.get_text())
        except Exception:continue
        stack=d if isinstance(d,list) else [d]
        while stack:
            x=stack.pop(0)
            if isinstance(x,list):stack.extend(x);continue
            if not isinstance(x,dict):continue
            if str(x.get('@type','')).lower()=='product' and clean(x.get('name')):names.append(clean(x.get('name')))
            for k in ('mainEntity','item','@graph'):
                c=x.get(k)
                if c:stack.extend(c if isinstance(c,list) else [c])
    seen=set();out=[]
    for x in names:
        k=norm(x)
        if k and k not in seen:seen.add(k);out.append(x)
    return out

def page_matches(html,query):
    q=set(tokens(query))
    if not q:return False
    return any(q.issubset(set(tokens(n))) and not any(norm(x) in norm(n) for x in NON_FRAGRANCE) for n in page_names(html))

def variants(html,name,url):
    soup=BeautifulSoup(html,'html.parser'); strings=[clean(x) for x in soup.stripped_strings if clean(x)]; out=[]; seen=set()
    for i,v in enumerate(strings):
        m=SIZE_FULL_RE.fullmatch(v)
        if not m:continue
        size=f'{m.group(1).replace(",",".")} ml'
        if size in seen:continue
        chunk=[]; sold=False
        for j in range(i+1,min(i+30,len(strings))):
            x=strings[j]
            if SIZE_FULL_RE.fullmatch(x):break
            chunk.append(x)
            if any(s in x.lower() for s in SOLD_OUT):sold=True;break
        p=price(' '.join(chunk))
        if sold or not p:continue
        seen.add(size); out.append({'store':STORE,'name':f'{name} {size}','price':p,'url':f'{url}#{size.replace(" ","-").lower()}','available':True,'availability':'in_stock','size':size})
    return out

def search(query):
    query=clean(query)
    if not query:return []
    s=requests.Session()
    try:
        cat=find_category(s,query)
        if not cat:return []
        r=get(s,cat)
        if not r:return []
        candidates=extract_candidates(r.text,query)
        if not candidates:return []
        result=[]; seen=set()
        for item in candidates[:12]:
            original=item['url'].split('#')[0].split('?')[0]
            page=get(s,original)
            if not page:continue
            # Verify the FINAL redirected page, not the original URL.
            final=page.url.split('#')[0].split('?')[0]
            if not page_matches(page.text,query):continue
            # Never expose the pre-redirect URL.
            if not url_match(final,query):continue
            for v in variants(page.text,item['name'],final):
                k=(v['url'],v['size'],v['price'])
                if k not in seen:seen.add(k);result.append(v)
        result.sort(key=lambda x: float(SIZE_RE.search(x['size']).group(1).replace(',','.')) if SIZE_RE.search(x['size']) else 9999)
        return result[:20]
    finally:s.close()
