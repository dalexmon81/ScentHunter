"""Opt-in catalog-first search API and browser demo."""
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse


router = APIRouter()


@lru_cache(maxsize=1)
def _engine():
    from sqlalchemy.engine import make_url

    from app.db import database_url, make_engine

    url = make_url(database_url())
    if url.get_backend_name() == "sqlite" and (
        not url.database or url.database == ":memory:" or not Path(url.database).is_file()
    ):
        raise HTTPException(status_code=503, detail="Canonical catalog is not provisioned")
    return make_engine()


@router.get("/search")
@router.get("/api/catalog/search")
def catalog_search(q: str = Query(min_length=1, max_length=120)):
    from sqlalchemy.orm import Session

    from app.search.catalog import search_catalog

    with Session(_engine()) as session:
        return search_catalog(session, q.strip())


@router.get("/api/catalog/status")
def catalog_status():
    from sqlalchemy.orm import Session

    from app.search.catalog import catalog_status as read_catalog_status

    with Session(_engine()) as session:
        return read_catalog_status(session)


@router.get("/catalog-demo", response_class=HTMLResponse, include_in_schema=False)
def catalog_demo():
    """Small browser UI for the read-only catalog-first pilot."""
    return HTMLResponse(_CATALOG_DEMO_HTML)


_CATALOG_DEMO_HTML = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ScentHunter · Catalogo</title>
<style>
:root{color-scheme:dark;--bg:#101216;--panel:#191d24;--line:#303744;--muted:#aab3c0;--text:#f5f7fa;--accent:#b7e0cf}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:900px;margin:0 auto;padding:32px 18px 60px}header{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:28px}
h1{font-size:clamp(28px,5vw,42px);margin:0;letter-spacing:-.04em}h2{font-size:19px;margin:0 0 10px}
p{color:var(--muted);margin:6px 0}.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;margin:14px 0}
.status{font-size:13px;padding:6px 10px;border:1px solid var(--line);border-radius:99px;color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.metric{padding:14px;background:#11151b;border-radius:12px}.metric strong{display:block;font-size:25px}.metric span{font-size:12px;color:var(--muted)}
form{display:flex;gap:10px;margin-top:14px}input{min-width:0;flex:1;background:#0e1116;border:1px solid var(--line);border-radius:10px;padding:13px;color:var(--text);font:inherit}
button{background:var(--accent);color:#122019;border:0;border-radius:10px;padding:0 20px;font:600 15px system-ui;cursor:pointer}
button:disabled{opacity:.5;cursor:wait}.hint{font-size:13px}.results{display:grid;gap:12px;margin-top:16px}.result{border:1px solid var(--line);border-radius:12px;padding:16px}.result h3{margin:0 0 4px;font-size:18px}.brand{color:var(--muted);font-size:13px}.offer{display:flex;justify-content:space-between;gap:12px;align-items:center;border-top:1px solid var(--line);padding-top:12px;margin-top:12px}.price{font-size:22px;font-weight:700}.offer a{color:var(--accent);word-break:break-all}.empty{color:var(--muted);padding:18px 0}.error{color:#ffb4a9}
@media(max-width:560px){header{align-items:flex-start;flex-direction:column}.metrics{grid-template-columns:1fr 1fr}form{flex-direction:column}button{padding:12px}}
</style>
</head>
<body><main>
<header><div><h1>ScentHunter</h1><p>Ricerca nel catalogo interno · demo catalog-first</p></div><span class="status" id="connection">Controllo catalogo…</span></header>
<section class="panel"><h2>Stato del catalogo</h2><div class="metrics">
<div class="metric"><strong id="products">—</strong><span>Profumi</span></div>
<div class="metric"><strong id="variants">—</strong><span>Varianti</span></div>
<div class="metric"><strong id="offers">—</strong><span>Offerte pubblicate</span></div>
</div><p class="hint" id="status-note">I dati vengono letti dal database catalog-first. Nessuno store viene interrogato durante la ricerca.</p></section>
<section class="panel"><h2>Cerca un profumo</h2><p>Prova con marca, nome, concentrazione o formato. Esempio: Dior Sauvage EDP 100 ml.</p>
<form id="search-form"><input id="query" maxlength="120" required placeholder="Cerca un profumo…" autocomplete="off"><button id="submit" type="submit">Cerca</button></form>
<div id="results" class="results" aria-live="polite"></div></section>
<p class="hint">Versione di prova: le offerte mostrate sono solo quelle validate, abbinate e aggiornate secondo le regole del catalogo.</p>
</main>
<script>
const el=id=>document.getElementById(id);
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}
async function loadStatus(){try{const r=await fetch('/api/catalog/status');if(!r.ok)throw new Error(r.status===503?'Catalogo non ancora provisionato':'Errore '+r.status);const s=await r.json();el('connection').textContent='Catalogo '+s.status;el('products').textContent=s.canonical_products??0;el('variants').textContent=s.canonical_variants??0;el('offers').textContent=s.published_offers??0;el('status-note').textContent='Aggiornamento dati: '+(s.freshness_window_hours??24)+' ore. Le offerte non aggiornate o non verificate non vengono mostrate.'}catch(e){el('connection').textContent='Non disponibile';el('status-note').textContent=e.message;el('status-note').className='hint error'}}
el('search-form').addEventListener('submit',async event=>{event.preventDefault();const q=el('query').value.trim();if(!q)return;const button=el('submit'),out=el('results');button.disabled=true;out.replaceChildren(node('p','empty','Ricerca nel catalogo…'));try{const r=await fetch('/api/catalog/search?q='+encodeURIComponent(q));const data=await r.json();if(!r.ok)throw new Error(data.detail||'Errore '+r.status);out.replaceChildren();if(!data.results?.length){out.append(node('p','empty','Nessun prodotto trovato nel catalogo.'));return}for(const item of data.results){const card=node('article','result');card.append(node('div','brand',item.brand));card.append(node('h3','',item.name));if(!item.offers?.length){card.append(node('p','empty','Prodotto presente, ma nessuna offerta verificata al momento.'))}for(const offer of item.offers){const row=node('div','offer');const details=node('div');details.append(node('strong','',offer.store));details.append(node('p','hint',offer.availability+' · aggiornato '+new Date(offer.captured_at).toLocaleString()));const link=node('a','', 'Apri offerta');link.href=offer.url;link.target='_blank';link.rel='noopener noreferrer';details.append(link);row.append(details,node('div','price',offer.price+' '+offer.currency));card.append(row)}out.append(card)}}catch(e){out.replaceChildren(node('p','error',e.message))}finally{button.disabled=false}});
loadStatus();
</script></body></html>"""
