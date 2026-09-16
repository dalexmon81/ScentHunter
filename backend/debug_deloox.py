from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote_plus

import requests
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])
BASE_FALLBACK = "https://www.deloox.be"

CHILD_CODE = r'''
import importlib, inspect, json, os, sys, time, traceback, requests

q = sys.argv[1]
try:
    m = importlib.import_module("scrapers.deloox.scraper")
    fn = getattr(m, "discover", None)
    name = "discover"
    if not callable(fn):
        fn = getattr(m, "_discover", None)
        name = "_discover"
    if not callable(fn):
        print(json.dumps({"ok":False,"stage":"no_discover"}))
        raise SystemExit(0)

    s = requests.Session()
    headers = dict(getattr(m, "HEADERS", {}) or {})
    if headers:
        s.headers.update(headers)
    started = time.monotonic()
    try:
        try:
            r = fn(s, q)
            call_style = "session_query"
        except TypeError as e:
            # Only retry if the function signature really appears to accept one argument.
            sig = str(inspect.signature(fn))
            if "session" in sig.lower():
                raise
            r = fn(q)
            call_style = "query_only"
    finally:
        s.close()

    out = {
        "ok": True,
        "name": name,
        "signature": str(inspect.signature(fn)),
        "call_style": call_style,
        "type": type(r).__name__,
        "count": len(r) if hasattr(r, "__len__") else None,
        "elapsed_ms": round((time.monotonic()-started)*1000),
    }
    if isinstance(r, (list, tuple)):
        out["first_items"] = repr(list(r)[:12])[:12000]
    elif isinstance(r, dict):
        out["first_items"] = repr(list(r.items())[:12])[:12000]
    else:
        out["first_items"] = repr(r)[:12000]
    print(json.dumps(out, ensure_ascii=False))
except Exception as e:
    print(json.dumps({
        "ok":False,
        "stage":"discover_child",
        "error":f"{type(e).__name__}: {e}",
        "traceback":traceback.format_exc(),
    }, ensure_ascii=False))
'''


def _fingerprint(m):
    path = getattr(m, "__file__", None)
    try:
        raw = open(path, "rb").read() if path else b""
        return {
            "file": path,
            "origin": getattr(getattr(m, "__spec__", None), "origin", None),
            "sha256": hashlib.sha256(raw).hexdigest() if raw else None,
            "lines": raw.count(b"\n") + 1 if raw else None,
            "size_bytes": len(raw) if raw else None,
        }
    except Exception as e:
        return {"file": path, "error": f"{type(e).__name__}: {e}"}


def _source(m, name):
    fn = getattr(m, name, None)
    if not callable(fn):
        return None
    try:
        return {
            "signature": str(inspect.signature(fn)),
            "source": inspect.getsource(fn)[:30000],
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _http(url, headers, timeout=6):
    t = time.monotonic()
    try:
        r = requests.get(url, headers=headers or None, timeout=timeout, allow_redirects=True)
        return {
            "status": r.status_code,
            "final_url": r.url,
            "bytes": len(r.content or b""),
            "elapsed_ms": round((time.monotonic()-t)*1000),
        }
    except Exception as e:
        return {
            "status": None,
            "elapsed_ms": round((time.monotonic()-t)*1000),
            "error": f"{type(e).__name__}: {e}",
        }


@router.get("/deloox-runtime-forensic-v3")
def deloox_runtime_forensic_v3(
    q: str = Query("Born in Roma", min_length=1),
    child_timeout: int = Query(15, ge=5, le=30),
):
    started = time.monotonic()
    try:
        import importlib
        m = importlib.import_module("scrapers.deloox.scraper")
        fp = _fingerprint(m)
        base = str(getattr(m, "BASE", None) or getattr(m, "BASE_URL", None) or BASE_FALLBACK).rstrip("/")
        headers = dict(getattr(m, "HEADERS", {}) or {})

        fn_name = "discover" if callable(getattr(m, "discover", None)) else "_discover" if callable(getattr(m, "_discover", None)) else None
        sources = {n: _source(m, n) for n in ("discover", "_discover", "_candidate_contexts", "_candidate_product_urls", "product_url", "relevant", "matches") if callable(getattr(m, n, None))}

        # Exactly ONE cheap HTTP probe. No product-page probes, no profiler, no multiprocessing.
        raw = _http(f"{base}/chercher.html?q={quote_plus(str(q).strip())}", headers, timeout=6)

        # Clean child process, started by subprocess rather than multiprocessing/fork.
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        t = time.monotonic()
        try:
            p = subprocess.run(
                [sys.executable, "-c", CHILD_CODE, str(q)],
                capture_output=True,
                text=True,
                timeout=child_timeout,
                env=env,
                cwd=os.getcwd(),
            )
            child_elapsed = round((time.monotonic()-t)*1000)
            stdout = (p.stdout or "").strip()
            stderr = (p.stderr or "").strip()
            try:
                child = json.loads(stdout.splitlines()[-1]) if stdout else {"ok":False,"stage":"empty_stdout"}
            except Exception:
                child = {"ok":False,"stage":"invalid_child_json","stdout_tail":stdout[-12000:]}
            child["returncode"] = p.returncode
            child["elapsed_ms_parent"] = child_elapsed
            if stderr:
                child["stderr_tail"] = stderr[-12000:]
        except subprocess.TimeoutExpired as e:
            child = {
                "ok": False,
                "timeout": True,
                "timeout_seconds": child_timeout,
                "stdout_tail": (e.stdout or "")[-12000:] if isinstance(e.stdout, str) else repr(e.stdout)[-12000:],
                "stderr_tail": (e.stderr or "")[-12000:] if isinstance(e.stderr, str) else repr(e.stderr)[-12000:],
                "elapsed_ms_parent": round((time.monotonic()-t)*1000),
            }

        return {
            "ok": True,
            "diagnostic": "DELOOX_RUNTIME_FORENSIC_V3",
            "read_only": True,
            "query": str(q).strip(),
            "runtime": fp,
            "base_url": base,
            "discover_function": fn_name,
            "functions": sources,
            "raw_search_page": raw,
            "discover_child": child,
            "total_elapsed_ms": round((time.monotonic()-started)*1000),
        }
    except Exception as e:
        return {
            "ok": False,
            "diagnostic": "DELOOX_RUNTIME_FORENSIC_V3",
            "error": f"{type(e).__name__}: {e}",
        }
