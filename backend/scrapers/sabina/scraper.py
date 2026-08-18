import re, json, sys, time
from urllib.parse import urljoin, urlparse, quote_plus
import requests
from bs4 import BeautifulSoup

BASE = 'https://www.sabina.com'
TIMEOUT = 15
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
    'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8,it;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
    'Referer': BASE + '/',
}
EXCLUDE_PATH = re.compile(r'/(?:content|ricerca|search|perquisition|recherche|marchi|marcas|marques|negozi|tiendas|boutiques|contatto|contact|faq|carrello|panier|cart|ordine|commande|stato-ordine|tracking|il-mio-conto|module)(?:/|$)', re.I)
PRICE_RE = re.compile(r'(?:€|EUR)\s*(\d{1,4}(?:[.,]\d{2})?)|(\d{1,4}(?:[.,]\d{2})?)\s*(?:€|EUR)', re.I)

def clean(x):
    return re.sub(r'\s+', ' ', str(x or '')).strip()

def norm(x):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', clean(x).lower())).strip()

def toks(x):
    return [t for t in norm(x).split() if len(t) > 1]

def all_tokens(text, query):
    q = toks(query)
    t = set(toks(text))
    return bool(q) and all(x in t for x in q)

def absolute(raw, base=BASE):
    if not raw: return ''
    u = urljoin(base, raw.strip().replace('\\/','/')).split('#')[0]
    return u

def is_same_domain(u):
    try: return urlparse(u).netloc.lower() in {'sabina.com','www.sabina.com'}
    except Exception: return False

def likely_product_url(u):
    if not u or not is_same_domain(u): return False
    p = urlparse(u).path
    if EXCLUDE_PATH.search(p): return False
    parts = [x for x in p.split('/') if x]
    if not parts: return False
    # Sabina product URLs are not assumed to have a fixed /product/ marker.
    # We accept locale + slug-like URLs and verify them on the real page.
    if len(parts) >= 2 and parts[0].lower() in {'it','fr','en','es','de','pt'}:
        slug = parts[-1]
        return len(slug) >= 4 and not slug.lower().endswith(('.xml','.json'))
    return False

def page_info(html):
    soup = BeautifulSoup(html, 'html.parser')
    title = clean(soup.title.get_text(' ', strip=True)) if soup.title else ''
    h1 = clean(soup.find('h1').get_text(' ', strip=True)) if soup.find('h1') else ''
    canonical = ''
    c = soup.find('link', rel=lambda x: x and 'canonical' in x)
    if c: canonical = absolute(c.get('href',''))
    text = clean(soup.get_text(' ', strip=True))
    json_products = []
    for s in soup.select('script[type="application/ld+json"]'):
        try:
            data=json.loads(s.get_text(strip=True))
        except Exception: continue
        stack=data if isinstance(data,list) else [data]
        while stack:
            x=stack.pop(0)
            if isinstance(x,list): stack.extend(x); continue
            if not isinstance(x,dict): continue
            typ=x.get('@type')
            if typ=='Product' or (isinstance(typ,list) and 'Product' in typ):
                json_products.append({k:x.get(k) for k in ('name','brand','sku','gtin13','url','offers')})
            for k in ('@graph','itemListElement'):
                if isinstance(x.get(k),list): stack.extend(x[k])
    return {'title':title,'h1':h1,'canonical':canonical,'text':text,'json_products':json_products}

def extract_links(html, query):
    soup=BeautifulSoup(html,'html.parser')
    found=[]; seen=set(); q=toks(query)
    for a in soup.find_all('a', href=True):
        u=absolute(a.get('href'))
        if not likely_product_url(u): continue
        label=clean(a.get_text(' ',strip=True))
        attrs=' '.join(clean(a.get(k,'')) for k in ('title','aria-label'))
        context=clean(label+' '+attrs+' '+u)
        score=sum(1 for t in q if t in set(toks(context)))
        if u not in seen:
            seen.add(u); found.append((score,u,label[:180]))
    return sorted(found,key=lambda x:(-x[0],x[1]))

def main(query):
    query=clean(query)
    if not query:
        print('SABINA_DIAG: ERROR empty query'); return 2
    s=requests.Session(); s.headers.update(HEADERS)
    report={'query':query,'tokens':toks(query),'probes':[],'candidate_urls':[],'verified':[]}
    print(f'SABINA_DIAG: START query={query!r}')
    print(f'SABINA_DIAG: TOKENS={report["tokens"]}')

    probes=[
        ('HOME', BASE+'/'),
        ('HOME_FR', BASE+'/fr/'),
        ('HOME_IT', BASE+'/it/'),
        ('SEARCH_FR_CONTROLLER', BASE+'/fr/recherche?controller=search&s='+quote_plus(query)),
        ('SEARCH_FR_S', BASE+'/fr/recherche?s='+quote_plus(query)),
        ('SEARCH_FR_QUERY', BASE+'/fr/perquisition?search_query='+quote_plus(query)),
        ('SEARCH_FR_SEARCH', BASE+'/fr/search?s='+quote_plus(query)),
        ('SEARCH_IT_CONTROLLER', BASE+'/it/ricerca?controller=search&s='+quote_plus(query)),
        ('SEARCH_IT_S', BASE+'/it/ricerca?s='+quote_plus(query)),
        ('SEARCH_IT_QUERY', BASE+'/it/ricerca?search_query='+quote_plus(query)),
        ('SITEMAP', BASE+'/sitemap.xml'),
        ('SITEMAP_INDEX', BASE+'/sitemap_index.xml'),
    ]

    all_candidate=[]; seen=set(); search_pages=0; blocked=0; errors=0
    for label,url in probes:
        t0=time.time()
        try:
            r=s.get(url,timeout=TIMEOUT,allow_redirects=True)
            body=r.text or ''
            ctype=(r.headers.get('content-type') or '').lower()
            rec={'label':label,'requested':url,'status':r.status_code,'final_url':r.url,'content_type':ctype,'bytes':len(r.content),'elapsed_ms':round((time.time()-t0)*1000)}
            if r.status_code in (403,429): blocked+=1
            if label.startswith('SEARCH_') and r.status_code < 400: search_pages += 1
            if 'html' in ctype or body.lstrip().startswith('<!DOCTYPE') or '<html' in body[:5000].lower():
                info=page_info(body)
                rec.update({'title':info['title'],'h1':info['h1'],'canonical':info['canonical'],'query_hits':sum(1 for x in report['tokens'] if x in norm(info['text'])),'json_product_count':len(info['json_products'])})
                links=extract_links(body,query)
                rec['candidate_links']=len(links)
                for score,u,lbl in links[:100]:
                    if u not in seen:
                        seen.add(u); all_candidate.append({'score':score,'url':u,'label':lbl,'source':label})
                if label.startswith('SEARCH_'):
                    print(f'SABINA_DIAG: {label} status={r.status_code} final={r.url} bytes={len(r.content)} hits={rec["query_hits"]} candidates={len(links)}')
            else:
                print(f'SABINA_DIAG: {label} status={r.status_code} type={ctype} bytes={len(r.content)} final={r.url}')
            report['probes'].append(rec)
            r.close()
        except Exception as e:
            errors+=1
            report['probes'].append({'label':label,'requested':url,'error':f'{type(e).__name__}: {e}'})
            print(f'SABINA_DIAG: {label} ERROR {type(e).__name__}: {e}')

    # sitemap URLs: parse all reachable XML and look for query tokens in URLs.
    sitemap_candidates=[]
    for rec in report['probes']:
        if rec.get('label','').startswith('SITEMAP') and rec.get('status',0) < 400:
            try:
                r=s.get(rec['final_url'],timeout=TIMEOUT,allow_redirects=True)
                txt=r.text
                for loc in re.findall(r'<loc>\s*(.*?)\s*</loc>',txt,re.I|re.S):
                    u=clean(loc)
                    if is_same_domain(u) and all_tokens(u,query):
                        sitemap_candidates.append(u)
                r.close()
            except Exception: pass
    for u in sitemap_candidates:
        if u not in seen and likely_product_url(u):
            seen.add(u); all_candidate.append({'score':len(report['tokens']),'url':u,'label':'sitemap','source':'sitemap'})

    all_candidate=sorted(all_candidate,key=lambda x:(-x['score'],x['url']))
    report['candidate_urls']=all_candidate[:100]
    print(f'SABINA_DIAG: CANDIDATES={len(all_candidate)}')
    for c in all_candidate[:20]:
        print(f'SABINA_DIAG: CANDIDATE score={c["score"]} source={c["source"]} url={c["url"]}')

    # Verify candidates directly on the real product page.
    verified=[]
    for c in all_candidate[:30]:
        u=c['url']
        try:
            r=s.get(u,timeout=TIMEOUT,allow_redirects=True)
            body=r.text or ''
            info=page_info(body) if r.status_code < 400 else {'title':'','h1':'','canonical':'','text':'','json_products':[]}
            names=[info['h1'],info['title']]+[clean(x.get('name')) for x in info['json_products'] if x.get('name')]
            names=[x for x in names if x]
            name=next((x for x in names if all_tokens(x,query)), names[0] if names else '')
            price=PRICE_RE.search(info['text'])
            match=bool(name and all_tokens(name,query))
            product_json=bool(info['json_products'])
            item={'url':u,'status':r.status_code,'final_url':r.url,'h1':info['h1'],'title':info['title'],'canonical':info['canonical'],'json_product':product_json,'name_match':match,'matched_name':name,'price_found':bool(price)}
            verified.append(item)
            print(f'SABINA_DIAG: VERIFY status={r.status_code} name_match={match} json_product={product_json} price={bool(price)} name={name!r} url={u}')
            r.close()
        except Exception as e:
            verified.append({'url':u,'error':f'{type(e).__name__}: {e}'})
            print(f'SABINA_DIAG: VERIFY_ERROR {u} {type(e).__name__}: {e}')
    report['verified']=verified
    successful=[x for x in verified if x.get('status',0)<400 and x.get('name_match')]

    # Definitive diagnosis, based only on observed stages.
    if successful:
        diagnosis='PRODUCT_FOUND_AND_VERIFIED'
    elif blocked or any(p.get('status') in (403,429) for p in report['probes']):
        diagnosis='SABINA_BLOCKS_HTTP_REQUESTS'
    elif search_pages==0:
        diagnosis='SEARCH_ENDPOINTS_UNREACHABLE_OR_REDIRECTED_TO_NON_SEARCH'
    elif not all_candidate:
        diagnosis='SEARCH_REACHED_BUT_NO_PRODUCT_URL_DISCOVERED'
    else:
        diagnosis='PRODUCT_URLS_DISCOVERED_BUT_PRODUCT_VERIFICATION_FAILED'

    report['diagnosis']=diagnosis
    report['summary']={
        'search_pages_ok':search_pages,
        'candidate_urls':len(all_candidate),
        'verified_pages':len(verified),
        'verified_matches':len(successful),
        'blocked_requests':blocked,
        'errors':errors,
    }
    print('')
    print('SABINA_DIAGNOSIS: '+diagnosis)
    print('SABINA_DIAG_SUMMARY: '+json.dumps(report['summary'],ensure_ascii=False))
    print('SABINA_DIAG_REPORT_BEGIN')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('SABINA_DIAG_REPORT_END')
    s.close()
    return 0

if __name__=='__main__':
    main(' '.join(sys.argv[1:]).strip() or 'Liquid brun')
