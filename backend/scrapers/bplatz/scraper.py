import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
STORE="Bplatz";BASE="https://en.bplatz.de";URL=BASE+"/collections/produkte"
HEADERS={"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"}
def _norm(v):
    v=str(v or "").lower()
    v=re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)"," ",v)
    v=re.sub(r"[^a-z0-9]+"," ",v)
    return re.sub(r"\s+"," ",v).strip()
def _match(a,b):return all(x in _norm(a) for x in _norm(b).split())
def _price(t):
    m=re.findall(r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)",t or "")
    v=[a or b for a,b in m if a or b]
    return v[-1].replace(".",",")+" €" if v else ""
def search(query):
    out=[];seen=set()
    for page in range(1,20):
        try:
            r=requests.get(URL,params={"page":page},headers=HEADERS,timeout=15)
            if r.status_code!=200:continue
        except requests.RequestException:continue
        soup=BeautifulSoup(r.text,"html.parser")
        for a in soup.find_all("a",href=True):
            name=" ".join(a.stripped_strings);link=urljoin(BASE,a.get("href",""))
            if not name or not _match(name,query) or "/products/" not in link or link in seen:continue
            seen.add(link)
            try:
                p=requests.get(link,headers=HEADERS,timeout=15)
                if p.status_code!=200:continue
                ps=BeautifulSoup(p.text,"html.parser");h1=ps.find("h1")
                pname=" ".join(h1.stripped_strings) if h1 else name
                price=_price(ps.get_text(" ",strip=True))
                if not price:continue
                meta=ps.find("meta",property="og:image")
                out.append({"store":STORE,"name":pname,"price":price,"url":link,"image":str(meta.get("content") or "") if meta else ""})
            except requests.RequestException:continue
            if len(out)>=10:return out
    return out
