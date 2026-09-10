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
        store:o.shop||o.store||"",
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


def _diag_wrap_function(module, name, events):
    """Wrap one scraper-internal function and record inputs/outputs.

    This deliberately avoids monkey-patching requests. We trace the scraper's
    own discovery/parser boundaries, which is the reliable information needed
    to locate where a product disappears.
    """
    original = getattr(module, name, None)
    if not callable(original):
        return lambda: None

    def wrapper(*args, **kwargs):
        started = time.monotonic()
        event = {"function": name, "started": round(started, 3)}
        try:
            value = original(*args, **kwargs)
            event["elapsed"] = round(time.monotonic() - started, 3)
            if isinstance(value, list):
                event["count"] = len(value)
                event["sample"] = [str(x)[:260] for x in value[:12]]
            elif isinstance(value, dict):
                event["count"] = 1
                event["sample"] = [str(value)[:260]]
            else:
                event["count"] = 0 if value is None else 1
                event["sample"] = [str(value)[:260]] if value is not None else []
            event["ok"] = True
            events.append(event)
            return value
        except Exception as exc:
            event["elapsed"] = round(time.monotonic() - started, 3)
            event["ok"] = False
            event["error"] = f"{type(exc).__name__}: {exc}"
            events.append(event)
            raise

    setattr(module, name, wrapper)

    def restore():
        setattr(module, name, original)

    return restore


def _diag_run_one(store, query):
    events = []
    logs = io.StringIO()
    started = time.monotonic()
    module = load_scraper(store)

    if store == "parfumzentrum":
        names = (
            "_fulltext_search_urls",
            "_category_fallback_urls",
            "_get_sitemap_urls",
            "_extract_product",
        )
    else:
        names = ("_discover", "_product")

    restores = []
    for name in names:
        restores.append(_diag_wrap_function(module, name, events))

    try:
        with contextlib.redirect_stdout(logs):
            result = module.search(query)
        rows = result if isinstance(result, list) else list(result or [])
        return {
            "store": store,
            "elapsed": round(time.monotonic() - started, 3),
            "result_count": len(rows),
            "results": rows,
            "events": events,
            "logs": logs.getvalue().splitlines(),
            "exception": "",
        }
    except Exception as exc:
        return {
            "store": store,
            "elapsed": round(time.monotonic() - started, 3),
            "result_count": 0,
            "results": [],
            "events": events,
            "logs": logs.getvalue().splitlines(),
            "exception": f"{type(exc).__name__}: {exc}",
        }
    finally:
        for restore in reversed(restores):
            restore()


def _diag_html(report):
    from html import escape

    css = """
    <style>
    body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#101114;color:#eee;margin:0;padding:28px}
    h1{font-size:42px;margin:0 0 8px}.sub{font-size:20px;color:#aeb3c0;margin-bottom:28px}
    .card{background:#1b1c20;border:1px solid #36373d;border-radius:24px;padding:30px;margin:20px 0;overflow:hidden}
    .big{font-size:42px;font-weight:800}.ok{color:#78e878}.bad{color:#ff7777}.muted{color:#aeb3c0}
    h2{font-size:27px;margin-top:30px} table{width:100%;border-collapse:collapse;font-size:16px}
    th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #303138;vertical-align:top}th{color:#aeb3c0}
    code{word-break:break-all}.url{max-width:520px}.event{margin:12px 0;padding:14px;border-radius:14px;background:#15161a;border:1px solid #303138}
    .fn{font-weight:800;font-size:19px}.sample{white-space:pre-wrap;word-break:break-word;color:#c8cbd3;margin-top:6px}
    summary{font-size:20px;font-weight:700;cursor:pointer;margin:12px 0}
    </style>
    """

    parts=[
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>ScentHunter — Diagnostico 2 store</title>",css,"</head><body>",
        "<h1>Diagnostico mirato</h1>",
        f"<div class='sub'>Query: <b>{escape(str(report['query']))}</b> — SOLO ParfumZentrum e Deloox.</div>",
    ]

    for item in report["stores"]:
        cls="bad" if item["exception"] else "ok"
        parts += ["<div class='card'>",
                  f"<div class='big'>{escape(str(item['store']))}</div>",
                  f"<div class='{cls}'>{'ERRORE' if item['exception'] else 'FINE'} — {item['elapsed']} s — {item['result_count']} risultati</div>"]
        if item["exception"]:
            parts.append(f"<p class='bad'><b>Eccezione:</b> {escape(str(item['exception']))}</p>")

        parts.append("<h2>Dove si perde</h2>")
        if item["events"]:
            for ev in item["events"]:
                status="OK" if ev.get("ok") else "KO"
                status_cls="ok" if ev.get("ok") else "bad"
                parts.append("<div class='event'>")
                parts.append(f"<div class='fn'>{escape(str(ev.get('function')))} — <span class='{status_cls}'>{status}</span> — {ev.get('elapsed',0)} s — count {ev.get('count',0)}</div>")
                if ev.get("error"):
                    parts.append(f"<div class='bad'>{escape(str(ev['error']))}</div>")
                if ev.get("sample"):
                    parts.append("<div class='sample'>"+escape("\n".join(str(x) for x in ev["sample"]))+"</div>")
                parts.append("</div>")
        else:
            parts.append("<div class='muted'>Nessun confine interno intercettato.</div>")

        parts.append("<h2>Risultati</h2>")
        if item["results"]:
            parts.append("<table><tr><th>Nome</th><th>Prezzo</th><th>Disponibilità</th></tr>")
            for row in item["results"][:20]:
                parts.append(f"<tr><td>{escape(str(row.get('name') or row.get('title') or ''))}</td><td>{escape(str(row.get('price') or row.get('price_value') or ''))}</td><td>{escape(str(row.get('available',row.get('availability',''))))}</td></tr>")
            parts.append("</table>")
        else:
            parts.append("<div class='bad'><b>ZERO risultati.</b> Il blocco è nelle funzioni sopra.</div>")

        if item["logs"]:
            parts += ["<details><summary>Log interni</summary><pre>",escape("\n".join(item["logs"][-120:])),"</pre></details>"]
        parts.append("</div>")

    parts.append("<div class='card muted'><b>Metodo:</b> nessun tracer HTTP. Il test avvolge direttamente le funzioni reali di discovery e parsing dei SOLI due scraper, quindi il punto di perdita viene mostrato senza JSON chilometrico.</div>")
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
