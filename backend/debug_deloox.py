from fastapi import APIRouter
import importlib
import inspect
import time

router = APIRouter(prefix="/api/debug", tags=["debug-deloox-stream-v2"])


@router.get("/deloox-stream-probe-v2")
def deloox_stream_probe_v2(q: str = "Born in Roma"):
    out = {
        "ok": True,
        "test": "TEST_8B_DELOOX_STREAM_TUPLE_PROBE",
        "query": q,
    }

    try:
        m = importlib.import_module("scrapers.deloox.scraper")
        sc = importlib.import_module("sitecustomize")

        discover = getattr(m, "discover", None)
        search_stream = getattr(sc, "search_stream", None)

        out["runtime"] = {
            "deloox_module_file": getattr(m, "__file__", ""),
            "sitecustomize_file": getattr(sc, "__file__", ""),
            "discover_callable": callable(discover),
            "search_stream_callable": callable(search_stream),
        }

        # Part A: inspect discover output shape without touching production code.
        t = time.perf_counter()
        candidates = discover(None, q)
        # The real discover needs a session, so if the call above fails, retry
        # using the same session construction pattern as the scraper.
        if candidates is None:
            candidates = []

        out["discover_probe"] = {
            "elapsed": round(time.perf_counter() - t, 3),
            "count": len(candidates),
        }

        tuple_lengths = {}
        unpack_ok = 0
        unpack_value_error = 0
        unpack_other_error = 0
        samples = []

        for url, info in candidates:
            try:
                n = len(info) if isinstance(info, (tuple, list)) else None
                key = str(n) if n is not None else type(info).__name__
                tuple_lengths[key] = tuple_lengths.get(key, 0) + 1

                try:
                    score, context = info
                    unpack_ok += 1
                    if len(samples) < 5:
                        samples.append({
                            "url": url,
                            "info_type": type(info).__name__,
                            "info": repr(info)[:500],
                            "unpack": "ok",
                        })
                except ValueError as exc:
                    unpack_value_error += 1
                    if len(samples) < 5:
                        samples.append({
                            "url": url,
                            "info_type": type(info).__name__,
                            "info": repr(info)[:500],
                            "unpack": "ValueError",
                            "error": str(exc),
                        })
                except Exception as exc:
                    unpack_other_error += 1
            except Exception:
                unpack_other_error += 1

        out["discover_probe"].update({
            "info_shape_counts": tuple_lengths,
            "unpack_ok": unpack_ok,
            "unpack_value_error": unpack_value_error,
            "unpack_other_error": unpack_other_error,
            "samples": samples,
        })

        # Part B: execute the actual stream adapter. It has its own session
        # handling, so this uses the exact public function signature and a
        # simple emitter.
        emitted = []
        emit_errors = []

        def emit(row):
            try:
                emitted.append(row)
            except Exception as exc:
                emit_errors.append({
                    "type": type(exc).__name__,
                    "error": str(exc),
                })

        stream_error = None
        stream_started = time.perf_counter()
        try:
            search_stream(q, emit)
        except Exception as exc:
            stream_error = {
                "type": type(exc).__name__,
                "error": str(exc),
            }

        urls = [
            r.get("url")
            for r in emitted
            if isinstance(r, dict) and r.get("url")
        ]

        out["actual_search_stream"] = {
            "elapsed": round(time.perf_counter() - stream_started, 3),
            "count": len(emitted),
            "urls": urls,
            "contains_ivory_donna": any("1400164" in u for u in urls),
            "contains_ivory_uomo": any("1400167" in u for u in urls),
            "emit_errors": emit_errors,
            "exception": stream_error,
        }

        return out

    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        return out
