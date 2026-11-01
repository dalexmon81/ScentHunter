import ast
import hashlib
import inspect
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()


@router.get("/diagnose-sabina-variant-callpath-read-only")
def diagnose_sabina_variant_callpath_read_only():
    import backend.catalog_engine as ce

    source_path = Path(inspect.getsourcefile(ce)).resolve()
    source = source_path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)

    functions = []
    calls = []
    variant_sql = []
    queue_sql = []

    def function_name(node):
        return getattr(node, "name", "<unknown>")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            body = "\n".join(lines[start - 1:end])

            functions.append({
                "name": function_name(node),
                "line_start": start,
                "line_end": end,
            })

            if (
                "refresh_url" in body
                or "hydration_queue" in body
                or "store_product_variants" in body
            ):
                relevant = []
                for i in range(start, min(end, len(lines)) + 1):
                    text = lines[i - 1]
                    if any(term in text.lower() for term in (
                        "refresh_url",
                        "hydration_queue",
                        "store_product_variants",
                        "variants",
                        "commit(",
                        "rollback(",
                        "except ",
                        "return ",
                    )):
                        relevant.append({
                            "line": i,
                            "text": text.strip()[:300],
                        })

                functions[-1]["relevant_lines"] = relevant

        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else ""
            )

            if name in ("refresh_url", "execute", "executemany"):
                try:
                    call_text = ast.get_source_segment(source, node) or ""
                except Exception:
                    call_text = ""

                if name == "refresh_url":
                    calls.append({
                        "line": node.lineno,
                        "call": call_text[:400],
                    })

                if name in ("execute", "executemany") and any(
                    term in call_text.lower()
                    for term in (
                        "store_product_variants",
                        "hydration_queue",
                    )
                ):
                    item = {
                        "line": node.lineno,
                        "call": call_text[:600],
                    }
                    if "store_product_variants" in call_text.lower():
                        variant_sql.append(item)
                    if "hydration_queue" in call_text.lower():
                        queue_sql.append(item)

    return {
        "ok": True,
        "diagnostic": "sabina-variant-callpath-read-only-v1",
        "read_only": True,
        "database_written": False,
        "http_requests": 0,
        "refresh_url_called": False,
        "source_file": str(source_path),
        "source_sha256": hashlib.sha256(
            source.encode("utf-8")
        ).hexdigest(),
        "refresh_url_source_sha256": hashlib.sha256(
            inspect.getsource(ce.refresh_url).encode("utf-8")
        ).hexdigest(),
        "refresh_url_call_sites": calls,
        "variant_sql_sites": variant_sql,
        "hydration_queue_sql_sites": queue_sql,
        "relevant_functions": [
            item for item in functions
            if "relevant_lines" in item
        ],
        "errors": [],
    }
