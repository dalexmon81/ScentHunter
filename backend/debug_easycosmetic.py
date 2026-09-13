from __future__ import annotations

import traceback
from fastapi import APIRouter, Query


router = APIRouter(
    prefix="/api/debug",
    tags=["debug"],
)


def _error(stage: str, exc: Exception, **extra):
    return {
        "diagnostic": True,
        "ok": False,
        "stage": stage,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exc(),
        **extra,
    }


@router.get("/easycosmetic")
def debug_easycosmetic(
    q: str = Query(..., min_length=2),
):
    """
    Diagnostica completa Easycosmetic.

    IMPORTANTE:
    lo scraper viene importato soltanto quando viene chiamato
    l'endpoint, così un problema di import non può rompere
    l'avvio di FastAPI.
    """

    try:
        from scrapers.easycosmetic.scraper import diagnose
    except Exception as exc:
        return _error(
            "import_scraper",
            exc,
            store="Easycosmetic",
            query=q,
        )

    try:
        result = diagnose(q)

        return {
            "diagnostic": True,
            "ok": True,
            "store": "Easycosmetic",
            "query": q,
            "result": result,
        }

    except Exception as exc:
        return _error(
            "diagnose",
            exc,
            store="Easycosmetic",
            query=q,
        )


@router.get("/easycosmetic-search")
def debug_easycosmetic_search(
    q: str = Query(..., min_length=2),
):
    """
    Testa ESCLUSIVAMENTE search().
    Non esegue parse_product().
    """

    try:
        from scrapers.easycosmetic.scraper import search
    except Exception as exc:
        return _error(
            "import_scraper",
            exc,
            store="Easycosmetic",
            query=q,
        )

    try:
        candidates = search(q)

        return {
            "diagnostic": True,
            "ok": True,
            "stage": "search",
            "store": "Easycosmetic",
            "query": q,
            "candidate_count": len(candidates or []),
            "candidates": candidates or [],
        }

    except Exception as exc:
        return _error(
            "search",
            exc,
            store="Easycosmetic",
            query=q,
        )


@router.get("/easycosmetic-product")
def debug_easycosmetic_product(
    url: str = Query(..., min_length=10),
):
    """
    Testa ESCLUSIVAMENTE parse_product() su un URL preciso.
    """

    try:
        from scrapers.easycosmetic.scraper import parse_product
    except Exception as exc:
        return _error(
            "import_scraper",
            exc,
            store="Easycosmetic",
            url=url,
        )

    try:
        product = parse_product(url)

        return {
            "diagnostic": True,
            "ok": True,
            "stage": "parse_product",
            "store": "Easycosmetic",
            "url": url,
            "product": product,
        }

    except Exception as exc:
        return _error(
            "parse_product",
            exc,
            store="Easycosmetic",
            url=url,
        )
