from fastapi import APIRouter
import importlib
import inspect
import time

router = APIRouter(prefix="/api/debug", tags=["debug-deloox-stream"])

@router.get("/deloox-stream-probe")
def deloox_stream_probe(q: str = "Born in Roma"):
    out = {"ok": True, "test": "TEST_8_DELOOX_STREAM_TUPLE_PROBE", "query": q}
    try:
        s = importlib.import_module("scrapers.deloox.scraper")
        sc = importlib.import_module("sitecustomize")
        importlib.reload(sc)

        out["runtime"] = {
            "scraper_file": getattr(s, "__file__", ""),
            "sitecustomize_file": getattr(sc, "__file__", ""),
            "discover_signature": str(inspect.signature(s.discover)),
            "search_stream_signature": str(inspect.signature(getattr(sc, "search_stream", None))),
        }

        # Reproduce ONLY the tuple unpack performed by the production
        # sitecustomize adapter. No production code is modified.
        t = time.perf_counter()
        candidates = s.discover(s.get(s.requests.Session(), "") if False else __import__('requests').Session(), q)
        # The expression above intentionally avoids any helper monkeypatching;
        # discover receives a normal requests.Session exactly as the adapter does.
        out["discover"] = {
            "elapsed": round(time.perf_counter() - t, 3),
            "count": len(candidates or []),
            "info_tuple_lengths": {},
            "unpack_ok": 0,
            "unpack_value_error": 0,
            "unpack_type_error": 0,
            "examples": [],
            "ivory": {"1400164": "not_seen", "1400167": "not_seen"},
        }

        for item in candidates or []:
            try:
                url, info = item
            except Exception as exc:
                out["discover"]["unpack_type_error"] += 1
                continue
            try:
                n = len(info)
                out["discover"]["info_tuple_lengths"][str(n)] = out["discover"]["info_tuple_lengths"].get(str(n), 0) + 1
            except Exception:
                pass
            try:
                score, context = info
                out["discover"]["unpack_ok"] += 1
                if len(out["discover"]["examples"]) < 5:
                    out["discover"]["examples"].append({"url": url, "info_type": type(info).__name__, "info_len": len(info), "score": score})
            except ValueError as exc:
                out["discover"]["unpack_value_error"] += 1
                if "1400164" in str(url): out["discover"]["ivory"]["1400164"] = "value_error"
                if "1400167" in str(url): out["discover"]["ivory"]["1400167"] = "value_error"
                if len(out["discover"]["examples"]) < 5:
                    out["discover"]["examples"].append({"url": url, "info_type": type(info).__name__, "info_len": len(info), "error": str(exc)})
            except TypeError as exc:
                out["discover"]["unpack_type_error"] += 1

        # Run the actual adapter and collect emitted rows. This is observational only.
        emitted = []
        t = time.perf_counter()
        stream_error = None
        try:
            result = sc.search_stream(q, lambda row: emitted.append(row) if isinstance(row, dict) else None)
            if result is not None:
                try:
                    for row in result:
                        if isinstance(row, dict):
                            emitted.append(row)
                except TypeError:
                    pass
        except Exception as exc:
            stream_error = f"{type(exc).__name__}: {exc}"

        urls = [str(r.get("url")) for r in emitted if isinstance(r, dict) and r.get("url")]
        out["actual_search_stream"] = {
            "elapsed": round(time.perf_counter() - t, 3),
            "count": len(emitted),
            "error": stream_error,
            "ivory_donna": any("1400164" in u for u in urls),
            "ivory_uomo": any("1400167" in u for u in urls),
            "urls": urls,
        }

        out["conclusion"] = {
            "tuple_shape_mismatch_proven": out["discover"]["unpack_value_error"] > 0,
            "all_discovered_infos_have_3_items": out["discover"]["info_tuple_lengths"] == {"3": out["discover"]["count"]},
            "stream_returned_fewer_than_discover": len(emitted) < out["discover"]["count"],
        }
        return out
    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        return out
