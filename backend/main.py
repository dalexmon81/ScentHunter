"""ScentHunter - single live search orchestrator.

Runtime architecture:
    frontend -> main.py -> 8 independent scrapers

There is deliberately no legacy SearchEngine, catalog index or secondary
orchestrator in the live path. Each store runs independently and publishes its
result as soon as it finishes. The frontend polls the job and redraws results
incrementally.
"""
from __future__ import annotations

import importlib
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

app = FastAPI(title="ScentHunter API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORES = [
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "notino",
]

STORE_LABELS = {
    "bplatz": "Bplatz",
    "deloox": "Deloox",
    "parfumcity": "ParfumCity",
    "parfumzentrum": "ParfumZentrum",
    "perfumemarket": "PerfumeMarket",
    "sabina": "Sabina",
    "orioudh": "Orioudh",
    "notino": "Notino",
}

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR.parent / "frontend" / "index.html"

# A store is allowed to finish later than the first visible results. The job
# remains alive long enough to collect the slowest real scraper, but the UI
# never waits for it before showing earlier stores.
STORE_DEADLINE_SECONDS = 60.0
JOB_RETENTION_SECONDS = 15 * 60
MAX_SEARCH_JOBS = 50

# Eight independent worker slots: one store cannot serialize another store.
STORE_EXECUTOR = ThreadPoolExecutor(
    max_workers=len(STORES),
    thread_name_prefix="scenthunter-store",
)

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def load_scraper(store: str):
    return importlib.import_module(f"scrapers.{store}.scraper")


def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace("€", "").replace("\xa0", " ")
        # Keep the common European decimal form.
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", ".")
        return float(text)
    except (TypeError, ValueError):
        return None


def _normalise_store(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().lower()
    aliases = {
        "bplatz": "bplatz",
        "bplatz.de": "bplatz",
        "deloox": "deloox",
        "parfumcity": "parfumcity",
        "parfum city": "parfumcity",
        "parfumzentrum": "parfumzentrum",
        "parfum zentrum": "parfumzentrum",
        "parfum-zentrum": "parfumzentrum",
        "perfumemarket": "perfumemarket",
        "perfume market": "perfumemarket",
        "sabina": "sabina",
        "orioudh": "orioudh",
        "orioudh.com": "orioudh",
        "notino": "notino",
    }
    return aliases.get(text, text)


def clean_result(item: Dict[str, Any], store: str) -> Dict[str, Any]:
    result = dict(item)
    machine_store = _normalise_store(
        result.get("store") or result.get("shop"),
        store,
    )
    result["store"] = machine_store
    result.setdefault(
        "shop",
        STORE_LABELS.get(machine_store, machine_store),
    )

    # Flatten the richer scraper schema when present. This keeps the frontend
    # independent of scraper-specific internal structures.
    attrs = result.get("attributes")
    if isinstance(attrs, dict):
        size_info = attrs.get("size_ml")
        if result.get("size_ml") in (None, "") and isinstance(size_info, dict):
            result["size_ml"] = size_info.get("value")

        conc_info = attrs.get("concentration")
        if result.get("concentration") in (None, "") and isinstance(conc_info, dict):
            result["concentration"] = conc_info.get("value")

    offer = result.get("offer")
    if isinstance(offer, dict):
        if result.get("price_value") in (None, ""):
            result["price_value"] = offer.get("price")
        if result.get("availability") in (None, ""):
            result["availability"] = offer.get("availability")

    source = result.get("source")
    if isinstance(source, dict):
        result.setdefault("url", source.get("url"))
        result.setdefault("image", source.get("image"))
        result.setdefault("brand", source.get("source_brand"))

    if "available" not in result:
        availability = str(result.get("availability") or "").lower()
        result["available"] = availability not in {
            "out_of_stock",
            "outofstock",
            "sold_out",
            "soldout",
            "unavailable",
        }

    if result.get("size_ml") in (None, ""):
        for key in ("volume_ml", "format_ml", "size"):
            value = result.get(key)
            if value not in (None, ""):
                parsed = _safe_float(value)
                if parsed is not None:
                    result["size_ml"] = parsed
                    break

    if "price_num" not in result:
        parsed = _safe_float(
            result.get("price_value")
            if result.get("price_value") not in (None, "")
            else result.get("price")
        )
        if parsed is not None:
            result["price_num"] = parsed

    return result


def result_key(item: Dict[str, Any]) -> tuple:
    store = _normalise_store(
        item.get("store") or item.get("shop"),
        "",
    )
    url = str(
        item.get("url")
        or item.get("product_url")
        or ""
    ).strip().lower()
    product_id = str(
        item.get("store_product_id")
        or item.get("product_id")
        or item.get("sku")
        or ""
    ).strip().lower()
    name = " ".join(
        str(item.get("name") or item.get("title") or "").split()
    ).lower()
    size = _safe_float(item.get("size_ml"))
    size_key = round(size, 3) if size is not None else ""
    identity = url or product_id or name
    return store, identity, size_key


def dedupe_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output = []
    for item in results:
        key = result_key(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def sort_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(item):
        available = item.get("available")
        price = _safe_float(item.get("price_num"))
        if available is False:
            rank = 2
        elif price is not None:
            rank = 0
        else:
            rank = 1
        return rank, price if price is not None else 999999.0

    return sorted(results, key=key)


def run_store(store: str, query: str) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        module = load_scraper(store)
        search = getattr(module, "search")
        raw = search(query)

        if raw is None:
            rows = []
        elif isinstance(raw, list):
            rows = raw
        elif isinstance(raw, tuple):
            rows = list(raw)
        else:
            try:
                rows = list(raw)
            except TypeError:
                rows = []

        cleaned = [
            clean_result(item, store)
            for item in rows
            if isinstance(item, dict)
        ]

        return {
            "store": store,
            "status": "ok" if cleaned else "empty",
            "elapsed": round(time.monotonic() - started, 3),
            "count": len(cleaned),
            "results": cleaned,
            "error": None,
        }

    except Exception as exc:
        traceback.print_exc()
        return {
            "store": store,
            "status": "error",
            "elapsed": round(time.monotonic() - started, 3),
            "count": 0,
            "results": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _publish_store(job_id: str, report: Dict[str, Any]) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return

        store = report["store"]

        # Ignore a late result after the store has already been marked timed out.
        previous = job["stores"].get(store)
        if previous and previous.get("status") == "timeout":
            return

        job["stores"][store] = {
            "status": report["status"],
            "elapsed": report["elapsed"],
            "count": report["count"],
        }

        if report.get("error"):
            job["errors"][store] = report["error"]
        else:
            job["errors"].pop(store, None)

        job["results"].extend(report["results"])
        job["results"] = sort_results(
            dedupe_results(job["results"])
        )

        completed_stores = sum(
            1
            for name in STORES
            if name in job["stores"]
        )
        job["completed"] = completed_stores >= len(STORES)


def _snapshot(job_id: str) -> Dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {
                "job_id": job_id,
                "query": "",
                "completed": True,
                "results": [],
                "comparisons": [],
                "errors": {"job": "job_not_found"},
                "stores": {},
            }

        return {
            "job_id": job["job_id"],
            "query": job["query"],
            "completed": job["completed"],
            "results": list(job["results"]),
            "comparisons": [],
            "errors": dict(job["errors"]),
            "stores": dict(job["stores"]),
        }


def _store_timeout_watcher(job_id: str, store: str, future, started: float):
    # This only marks the store as timed out. Python cannot safely kill an
    # already-running scraper thread. Individual scraper HTTP timeouts remain
    # responsible for releasing the worker.
    deadline = started + STORE_DEADLINE_SECONDS
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)

    if future.done():
        return

    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        if store in job["stores"]:
            return

        job["stores"][store] = {
            "status": "timeout",
            "elapsed": round(time.monotonic() - started, 3),
            "count": 0,
        }
        job["errors"][store] = (
            f"Timeout: {STORE_DEADLINE_SECONDS:.0f}s"
        )

        job["completed"] = all(
            name in job["stores"]
            for name in STORES
        )


def _run_store_for_job(job_id: str, store: str, query: str):
    started = time.monotonic()
    future = STORE_EXECUTOR.submit(run_store, store, query)

    # A separate lightweight watcher prevents a broken scraper from keeping
    # the job logically open forever.
    threading.Thread(
        target=_store_future_watcher,
        args=(job_id, store, future, started),
        daemon=True,
        name=f"watch-{store}-{job_id[:6]}",
    ).start()


def _store_future_watcher(job_id: str, store: str, future, started: float):
    deadline = started + STORE_DEADLINE_SECONDS

    while True:
        if future.done():
            try:
                report = future.result()
            except Exception as exc:
                report = {
                    "store": store,
                    "status": "error",
                    "elapsed": round(time.monotonic() - started, 3),
                    "count": 0,
                    "results": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            _publish_store(job_id, report)
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job or store in job["stores"]:
                    return

                job["stores"][store] = {
                    "status": "timeout",
                    "elapsed": round(time.monotonic() - started, 3),
                    "count": 0,
                }
                job["errors"][store] = (
                    f"Timeout: {STORE_DEADLINE_SECONDS:.0f}s"
                )
                job["completed"] = all(
                    name in job["stores"]
                    for name in STORES
                )
            return

        time.sleep(min(0.15, remaining))


def _cleanup_jobs():
    while True:
        time.sleep(60)
        cutoff = time.time() - JOB_RETENTION_SECONDS
        with JOBS_LOCK:
            old = [
                job_id
                for job_id, job in JOBS.items()
                if job.get("started_at", 0) < cutoff
            ]
            for job_id in old:
                JOBS.pop(job_id, None)

            if len(JOBS) > MAX_SEARCH_JOBS:
                ordered = sorted(
                    JOBS.items(),
                    key=lambda pair: pair[1].get("started_at", 0),
                )
                for job_id, _ in ordered[:-MAX_SEARCH_JOBS]:
                    JOBS.pop(job_id, None)


threading.Thread(
    target=_cleanup_jobs,
    daemon=True,
    name="scenthunter-job-cleanup",
).start()


def _new_job(query: str) -> str:
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "query": query,
            "started_at": time.time(),
            "completed": False,
            "results": [],
            "comparisons": [],
            "errors": {},
            "stores": {},
        }

    # Submit every store immediately. There is no aggregate wait.
    for store in STORES:
        _run_store_for_job(job_id, store, query)

    return job_id


def _inject_progressive_frontend(html: str) -> str:
    """Replace the frontend's blocking /search click with job polling.

    Keeping this tiny adapter in main.py lets us fix the live UX without
    touching the large, working visual frontend file.
    """
    script = r"""
<script>
(function(){
  const oldButton=document.getElementById("searchButton");
  const oldInput=document.getElementById("query");
  if(!oldButton||!oldInput)return;

  const button=oldButton.cloneNode(true);
  const input=oldInput.cloneNode(true);
  oldButton.replaceWith(button);
  oldInput.replaceWith(input);

  let activeJob="";
  let polling=false;

  async function readJSON(url){
    let lastError=null;
    for(let attempt=0;attempt<4;attempt++){
      try{
        const response=await fetch(url,{headers:{"Accept":"application/json"}});
        if(!response.ok)throw new Error("HTTP "+response.status);
        return await response.json();
      }catch(error){
        lastError=error;
        if(attempt<3){
          await new Promise(resolve=>setTimeout(resolve,700));
        }
      }
    }
    throw lastError||new Error("Request failed");
  }

  function renderIncremental(data){
    const groups=shGroupData(data);
    showProducts(groups);
    refreshWishlistFromResults(
      groups.flatMap(g=>g.offers.map(o=>({
        name:g.name||"",
        brand:g.brand||"",
        price:shPrice(o),
        price_value:o.price_value,
        store:o.store||"",
        url:o.url||""
      })))
    );

    // Progress counters and store error messages are intentionally hidden.
    // Results themselves appear progressively as stores finish.
    statusBox.textContent="";
    errorsBox.innerHTML="";
  }

  async function progressiveSearch(){
    const q=input.value.trim();
    if(!q){
      statusBox.textContent="Scrivi il nome di un profumo.";
      resultsBox.innerHTML="";
      errorsBox.innerHTML="";
      return;
    }
    if(polling)return;

    polling=true;
    button.disabled=true;
    button.textContent="Cerco…";
    statusBox.textContent="";
    resultsBox.innerHTML="";
    errorsBox.innerHTML="";
    document.getElementById("searchOutput").scrollIntoView({
      behavior:"smooth",
      block:"start"
    });

    try{
      const started=await readJSON(
        backend()+"/search-start?q="+encodeURIComponent(q)
      );
      activeJob=started.job_id;
      let lastSignature="";

      while(activeJob){
        const data=await readJSON(
          backend()+"/search-status/"+encodeURIComponent(activeJob)
        );

        const signature=JSON.stringify([
          data.completed,
          data.results,
          data.stores,
          data.errors
        ]);

        if(signature!==lastSignature){
          lastSignature=signature;
          renderIncremental(data);
        }

        if(data.completed)break;
        await new Promise(resolve=>setTimeout(resolve,350));
      }

      statusBox.textContent="";
    }catch(error){
      console.error(error);
      statusBox.textContent="";
    }finally{
      polling=false;
      activeJob="";
      button.disabled=false;
      button.textContent="Cerca";
    }
  }

  button.addEventListener("click",progressiveSearch);
  input.addEventListener("keydown",function(event){
    if(event.key==="Enter"){
      event.preventDefault();
      progressiveSearch();
    }
  });

  window.searchPerfume=progressiveSearch;
})();
</script>
"""
    marker = "</body>"
    if marker in html:
        return html.replace(marker, script + "\n" + marker, 1)
    return html + script


def _frontend_response():
    if not FRONTEND_INDEX.exists():
        return HTMLResponse(
            "<h1>ScentHunter frontend missing</h1>",
            status_code=500,
        )
    html = FRONTEND_INDEX.read_text(
        encoding="utf-8",
        errors="replace",
    )
    return HTMLResponse(
        _inject_progressive_frontend(html),
        media_type="text/html",
    )


@app.get("/")
def root():
    return _frontend_response()


@app.get("/frontend")
def frontend():
    return _frontend_response()


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "architecture": "single-main-plus-8-independent-scrapers",
        "stores": STORES,
    }


@app.get("/search-start")
def search_start(q: str):
    query = str(q or "").strip()
    if not query:
        return {
            "job_id": "",
            "query": "",
            "completed": True,
            "results": [],
            "comparisons": [],
            "errors": {},
            "stores": {},
        }

    return _snapshot(_new_job(query))


@app.get("/search-status/{job_id}")
def search_status_path(job_id: str):
    return _snapshot(job_id)


@app.get("/search-status")
def search_status_query(job_id: str):
    return _snapshot(job_id)


@app.get("/search")
def search_perfume(q: str):
    """Compatibility endpoint for direct/API callers.

    The web UI uses /search-start + /search-status. This endpoint intentionally
    returns only when every store has finished, so API clients that expect the
    old one-shot contract keep working.
    """
    query = str(q or "").strip()
    if not query:
        return {
            "query": "",
            "count": 0,
            "results": [],
            "comparisons": [],
            "errors": {},
            "stores": {},
        }

    job_id = _new_job(query)
    deadline = time.monotonic() + STORE_DEADLINE_SECONDS + 5.0

    while time.monotonic() < deadline:
        snapshot = _snapshot(job_id)
        if snapshot["completed"]:
            results = sort_results(
                dedupe_results(snapshot["results"])
            )
            return {
                "query": query,
                "count": len(results),
                "results": results,
                "comparisons": [],
                "errors": snapshot["errors"],
                "stores": snapshot["stores"],
            }
        time.sleep(0.15)

    snapshot = _snapshot(job_id)
    results = sort_results(
        dedupe_results(snapshot["results"])
    )
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "comparisons": [],
        "errors": snapshot["errors"],
        "stores": snapshot["stores"],
    }


@app.get("/test-store")
def test_store(store: str, q: str):
    store = str(store or "").strip().lower()
    if store not in STORES:
        return {
            "ok": False,
            "store": store,
            "error": "unknown_store",
            "stores": STORES,
        }

    report = run_store(
        store,
        str(q or "").strip(),
    )
    return {
        "ok": report["status"] != "error",
        "store": store,
        "query": str(q or "").strip(),
        **report,
    }


@app.get("/diagnose-stores")
def diagnose_stores(q: str = "Liquid Brun"):
    """Sequentially report every store for diagnostics only.

    The live UI never uses this route.
    """
    query = str(q or "").strip()
    reports = [
        run_store(store, query)
        for store in STORES
    ]
    return {
        "ok": True,
        "architecture": "single-main-plus-8-independent-scrapers",
        "query": query,
        "stores": reports,
        "total_count": sum(
            item.get("count", 0)
            for item in reports
        ),
    }

# ---------------------------------------------------------------------------
# TARGETED DIAGNOSTIC — ONLY PARFUMZENTRUM + DELOOX
# ---------------------------------------------------------------------------

import contextlib
import io
from types import SimpleNamespace


class _TraceHTTP:
    """Global HTTP tracer: catches requests.get AND every requests.Session()."""
    def __init__(self, real_request, trace, label):
        self.real_request = real_request
        self.trace = trace
        self.label = label

    def __call__(self, session, method, url, *args, **kwargs):
        started = time.monotonic()
        try:
            response = self.real_request(session, method, url, *args, **kwargs)
            body = getattr(response, "text", "") or ""
            clue = _http_clue(body, self.label, url)
            self.trace.append({
                "label": self.label,
                "method": str(method).upper(),
                "url": str(url),
                "status": getattr(response, "status_code", None),
                "seconds": round(time.monotonic() - started, 3),
                "bytes": len(getattr(response, "content", b"") or b""),
                "error": "",
                "clue": clue,
            })
            return response
        except Exception as exc:
            self.trace.append({
                "label": self.label,
                "method": str(method).upper(),
                "url": str(url),
                "status": None,
                "seconds": round(time.monotonic() - started, 3),
                "bytes": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "clue": "",
            })
            raise


def _http_clue(body, store, url):
    """Small parser clue for product responses; never stores full HTML."""
    if not body:
        return "EMPTY"
    soup = BeautifulSoup(body, "html.parser")
    title = soup.find("title")
    h1 = soup.find("h1")
    title_text = " ".join(title.stripped_strings) if title else ""
    h1_text = " ".join(h1.stripped_strings) if h1 else ""
    low = body.lower()
    markers = []
    for marker in ("captcha", "cloudflare", "access denied", "just a moment", "bot verification"):
        if marker in low:
            markers.append(marker)
    if "/product/" in str(url).lower() or "/produit/" in str(url).lower() or "_z" in str(url).lower():
        if not h1_text:
            return "PRODUCT: NO_H1" + (" | " + ",".join(markers) if markers else "")
        return "PRODUCT: H1=" + h1_text[:140]
    if markers:
        return "PAGE: " + ",".join(markers)
    return ("PAGE: H1=" + h1_text[:100]) if h1_text else ("PAGE: TITLE=" + title_text[:100] if title_text else "PAGE: OK")


def _diag_run_one(store, query):
    trace = []
    stdout = io.StringIO()
    started = time.monotonic()
    module = load_scraper(store)
    import requests as _requests_lib
    original_request = _requests_lib.sessions.Session.request

    tracer = _TraceHTTP(original_request, trace, store)
    try:
        _requests_lib.sessions.Session.request = tracer
        with contextlib.redirect_stdout(stdout):
            result = module.search(query)
        rows = result if isinstance(result, list) else list(result or [])
        return {
            "store": store,
            "elapsed": round(time.monotonic() - started, 3),
            "result_count": len(rows),
            "results": rows,
            "trace": trace,
            "logs": stdout.getvalue().splitlines(),
            "exception": "",
        }
    except Exception as exc:
        return {
            "store": store,
            "elapsed": round(time.monotonic() - started, 3),
            "result_count": 0,
            "results": [],
            "trace": trace,
            "logs": stdout.getvalue().splitlines(),
            "exception": f"{type(exc).__name__}: {exc}",
        }
    finally:
        _requests_lib.sessions.Session.request = original_request


def _diag_stage(url):
    value = str(url or "").lower()
    if "fulltext_search" in value:
        return "RICERCA NATIVA"
    if "search" in value:
        return "RICERCA"
    if "sitemap" in value:
        return "SITEMAP"
    if "/categorie/" in value or "/category" in value or "product-line" in value:
        return "CATEGORIA"
    if "/product/" in value or "/produit/" in value or "_z" in value:
        return "PRODOTTO"
    return "ALTRO"


def _diag_group_trace(trace):
    groups = {}
    for item in trace:
        stage = _diag_stage(item.get("url"))
        bucket = groups.setdefault(stage, {
            "calls": 0, "seconds": 0.0, "ok": 0, "bad": 0, "bytes": 0
        })
        bucket["calls"] += 1
        bucket["seconds"] += item.get("seconds", 0.0) or 0.0
        bucket["bytes"] += item.get("bytes", 0) or 0
        status = item.get("status")
        if status is not None and 200 <= status < 400:
            bucket["ok"] += 1
        else:
            bucket["bad"] += 1
    for bucket in groups.values():
        bucket["seconds"] = round(bucket["seconds"], 3)
    return groups


def _diag_html(report):
    from html import escape

    css = """
    <style>
    body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;
         margin:0;background:#101114;color:#eee;padding:18px}
    h1{font-size:21px;margin:0 0 5px}
    h2{font-size:17px;margin:22px 0 9px}
    .sub{color:#aeb2bb;margin-bottom:16px}
    .card{background:#191b20;border:1px solid #30333a;border-radius:14px;
          padding:15px;margin:12px 0}
    .ok{color:#7ee787}.bad{color:#ff7b72}.muted{color:#9da1aa}
    .big{font-size:26px;font-weight:700}
    table{width:100%;border-collapse:collapse;font-size:12px}
    th,td{padding:7px 6px;border-bottom:1px solid #2a2d33;text-align:left;
           vertical-align:top}
    th{color:#b9bec8}
    code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10px;
         word-break:break-all}
    .url{max-width:520px;word-break:break-all}
    </style>
    """

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>ScentHunter — Diagnostico 2 store</title>",
        css, "</head><body>",
        "<h1>Diagnostico mirato</h1>",
        f"<div class='sub'>Query: <b>{escape(report['query'])}</b> — "
        "eseguiti SOLO ParfumZentrum e Deloox.</div>",
    ]

    for item in report["stores"]:
        cls = "bad" if item["exception"] else "ok"
        parts.append("<div class='card'>")
        parts.append(
            f"<div class='big'>{escape(item['store'])}</div>"
            f"<div class='{cls}'>{'ERRORE' if item['exception'] else 'FINE'}"
            f" — {item['elapsed']} s — {item['result_count']} risultati</div>"
        )
        if item["exception"]:
            parts.append(
                f"<p class='bad'><b>Eccezione:</b> {escape(item['exception'])}</p>"
            )

        groups = _diag_group_trace(item["trace"])
        parts.append("<h2>Dove si perdono</h2>")
        if groups:
            parts.append(
                "<table><tr><th>Fase</th><th>Chiamate</th>"
                "<th>Tempo HTTP</th><th>OK</th><th>KO</th><th>Dati</th></tr>"
            )
            for stage, data in groups.items():
                parts.append(
                    "<tr>"
                    f"<td><b>{escape(stage)}</b></td><td>{data['calls']}</td>"
                    f"<td>{data['seconds']} s</td><td>{data['ok']}</td>"
                    f"<td>{data['bad']}</td><td>{data['bytes']} B</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<div class='muted'>Nessuna richiesta HTTP intercettata.</div>")

        parts.append("<h2>Risultati</h2>")
        if item["results"]:
            parts.append(
                "<table><tr><th>Nome</th><th>Prezzo</th>"
                "<th>Disponibilità</th></tr>"
            )
            for row in item["results"][:20]:
                name = row.get("name") or row.get("title") or ""
                price = row.get("price") or row.get("price_value") or ""
                avail = row.get("available", row.get("availability", ""))
                parts.append(
                    f"<tr><td>{escape(str(name))}</td><td>{escape(str(price))}</td>"
                    f"<td>{escape(str(avail))}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append(
                "<div class='bad'><b>ZERO risultati.</b> "
                "Guarda il trace: così distinguiamo discovery, fetch o filtro.</div>"
            )

        parts.append("<details><summary>Trace HTTP completo</summary>")
        if item["trace"]:
            parts.append(
                "<table><tr><th>#</th><th>Fase</th><th>Tempo</th>"
                "<th>Status</th><th>Byte</th><th>URL</th><th>Indizio</th><th>Errore</th></tr>"
            )
            for i, call in enumerate(item["trace"], 1):
                status = call["status"]
                status_cls = "ok" if status and 200 <= status < 400 else "bad"
                parts.append(
                    "<tr>"
                    f"<td>{i}</td><td>{escape(_diag_stage(call['url']))}</td>"
                    f"<td>{call['seconds']} s</td>"
                    f"<td class='{status_cls}'>{escape(str(status) if status is not None else "—")}</td>"
                    f"<td>{call['bytes']}</td>"
                    f"<td class='url'><code>{escape(str(call['url']))}</code></td>"
                    f"<td>{escape(str(call.get('clue') or ""))}</td>"
                    f"<td class='bad'>{escape(str(call['error']))}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<div class='muted'>Nessuna richiesta.</div>")
        parts.append("</details>")

        if item["logs"]:
            parts.append("<details><summary>Log interni</summary><pre>")
            parts.append(escape("\n".join(item["logs"][-100:])))
            parts.append("</pre></details>")

        parts.append("</div>")

    parts.append(
        "<div class='card muted'><b>Diagnosi:</b> "
        "RICERCA/ SITEMAP = discovery; PRODOTTO = download/pagina; "
        "risultati = parsing/filtro. Nessun altro negozio viene eseguito.</div>"
    )
    parts.append("</body></html>")
    return "".join(parts)


@app.get("/diagnose-two")
def diagnose_two(q: str = "Liquid Brun"):
    query = str(q or "").strip() or "Liquid Brun"
    return HTMLResponse(
        _diag_html({
            "query": query,
            "stores": [
                _diag_run_one("parfumzentrum", query),
                _diag_run_one("deloox", query),
            ],
        }),
        media_type="text/html",
    )


@app.get("/suggest")
def suggest(q: str):
    # Autocomplete is intentionally not part of the live frontend.
    return {
        "query": str(q or "").strip(),
        "count": 0,
        "suggestions": [],
    }
