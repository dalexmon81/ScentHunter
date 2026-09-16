from fastapi import APIRouter
import importlib, inspect, re, traceback
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

router = APIRouter(prefix='/api/debug', tags=['debug-deloox-runtime'])
BASE = 'https://www.deloox.be'
QUERY = 'Born in Roma'
KNOWN = [
 'https://www.deloox.be/produit/1400164/valentino-donna-born-in-roma-ivory-eau-de-parfum-limited-edition-100-ml.html',
 'https://www.deloox.be/produit/1400167/born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html',
 'https://www.deloox.be/produit/1359237/born-in-roma-the-gold-uomo-eau-de-toilette-100-ml.html',
]

def _src(m,name):
    fn=getattr(m,name,None)
    if not callable(fn): return {'callable':False}
    try:
        lines,start=inspect.getsourcelines(fn)
        return {'callable':True,'signature':str(inspect.signature(fn)),'start_line':start,'source':''.join(lines)}
    except Exception as e: return {'callable':True,'error':repr(e)}

def _url_variants(html):
    raw=[]
    patterns={
      'regex_current': r'(?:https?:\\/\\/[^"\'<>\s]+)?/produit/\d+/[^"\'<>\s?#]+',
      'regex_normal': r'(?:https?://[^"\'<>\s]+)?/produit/\d+/[^"\'<>\s?#]+',
    }
    for label,pat in patterns.items():
        try: raw += [(label,x) for x in re.findall(pat,html,re.I)]
        except Exception as e: raw.append((label,'ERROR '+repr(e)))
    soup=BeautifulSoup(html,'html.parser')
    anchors=[]
    for a in soup.find_all('a',href=True):
        h=a.get('href')
        if '/produit/' in h.lower(): anchors.append(h)
    return raw, anchors

@router.get('/deloox-runtime-full-debug')
def full_debug(q: str = QUERY):
    out={'ok':True,'test':'DELOOX_RUNTIME_FULL_DEBUG_V7','query':q,'pages':[],'pipeline':{},'discover':{},'source':{}}
    try:
        m=importlib.import_module('scrapers.deloox.scraper')
        for n in ['is_born_in_roma_query','born_in_roma_slug','excluded_product_slug','is_product_url','product_url','relevant','discover','_candidate_contexts','_row_from_card','parse_product']:
            out['source'][n]=_src(m,n)
        s=requests.Session(); s.headers.update(getattr(m,'HEADERS',{}))
        all_urls=set(); raw_detail={}; anchor_urls=set(); regex_current=set(); regex_normal=set()
        for page in range(1,5):
            endpoint=f"{BASE}/chercher.html?q={quote_plus(q)}" + (f'&page={page}' if page>1 else '')
            try:
                r=s.get(endpoint,timeout=(4,8),allow_redirects=True)
                html=r.text or ''
                raw,anchors=_url_variants(html)
                for label,x in raw:
                    if x.startswith('ERROR'): continue
                    u=x.replace('\\/','/')
                    if u.startswith('/'): u=urljoin(BASE+'/',u)
                    u=u.split('#',1)[0].split('?',1)[0]
                    if 'regex_current'==label: regex_current.add(u)
                    if 'regex_normal'==label: regex_normal.add(u)
                for h in anchors:
                    u=h.replace('\\/','/')
                    if u.startswith('/'): u=urljoin(BASE+'/',u)
                    u=u.split('#',1)[0].split('?',1)[0]
                    anchor_urls.add(u)
                born=[]
                for u in sorted(anchor_urls | regex_normal | regex_current):
                    if 'born-in-roma' in u.lower() or 'born-in-roma' in u.lower().replace('_','-'):
                        born.append(u)
                out['pages'].append({'page':page,'status':r.status_code,'final_url':r.url,'html_length':len(html),'regex_current_count':len(regex_current),'regex_normal_count':len(regex_normal),'anchor_product_url_count':len(anchor_urls),'born_slug_text_count':len(born)})
                for u in born: all_urls.add(u)
            except Exception as e:
                out['pages'].append({'page':page,'error':repr(e)})
        def test(u):
            vals={}
            for n in ['is_product_url','product_url','born_in_roma_slug','excluded_product_slug']:
                try:
                    if n=='product_url': vals[n]=getattr(m,n)(u)
                    else: vals[n]=bool(getattr(m,n)(u))
                except Exception as e: vals[n]='ERROR '+repr(e)
            return vals
        details={u:test(u) for u in sorted(all_urls)}
        out['pipeline']['raw_unique_urls']=len(all_urls)
        out['pipeline']['details']=details
        for key in ['is_product_url','born_in_roma_slug','excluded_product_slug']:
            passed=[u for u,d in details.items() if d.get(key) is True]
            out['pipeline'][key+'_pass_count']=len(passed)
            out['pipeline'][key+'_fail_urls']=[u for u,d in details.items() if d.get(key) is not True]
        direct=[u for u,d in details.items() if d.get('is_product_url') is True and d.get('born_in_roma_slug') is True and d.get('excluded_product_slug') is False]
        out['pipeline']['direct_candidate_count']=len(direct)
        out['pipeline']['direct_candidates']=direct
        # Compare actual discover, but only after all non-destructive probes.
        try:
            cand=m.discover(s,q)
            out['discover']['count']=len(cand) if cand is not None else None
            out['discover']['items']=[]
            if cand:
                for item in cand:
                    try:
                        u,info=item
                        out['discover']['items'].append({'url':u,'info_repr':repr(info),'info_type':type(info).__name__,'info_len':len(info) if hasattr(info,'__len__') else None})
                    except Exception as e: out['discover']['items'].append({'repr':repr(item),'error':repr(e)})
            got={x.get('url') for x in out['discover']['items'] if x.get('url')}
            out['discover']['missing_direct_candidates']=sorted(set(direct)-got)
            out['discover']['extra_vs_direct']=sorted(got-set(direct))
        except Exception as e:
            out['discover']={'error':repr(e),'traceback':traceback.format_exc()}
        # Probe product pages independently, proving whether product parsing can recover any URL.
        pp=[]
        for u in direct[:12]:
            try:
                r=s.get(u,timeout=(4,8),allow_redirects=True)
                soup=BeautifulSoup(r.text or '','html.parser')
                ld=[]
                for tag in soup.find_all('script',type=lambda x: x and 'ld+json' in x.lower()):
                    txt=tag.string or tag.get_text()
                    if 'Product' in txt and ('price' in txt.lower() or 'offers' in txt.lower()): ld.append(txt[:1200])
                pp.append({'url':u,'status':r.status_code,'final_url':r.url,'html_length':len(r.text or ''),'jsonld_product_snippets':ld[:2]})
            except Exception as e: pp.append({'url':u,'error':repr(e)})
        out['product_page_probe']=pp
    except Exception as e:
        out['ok']=False; out['error']=repr(e); out['traceback']=traceback.format_exc()
    return out
