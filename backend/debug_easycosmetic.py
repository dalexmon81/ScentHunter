from __future__ import annotations

from fastapi import APIRouter, Query

from scrapers.easycosmetic.scraper import diagnose, search, parse_product


router = APIRouter(
    prefix="/api/debug",
    tags=["debug"],
)


@router.get("/easycosmetic")
def debug_easycosmetic(
    q: str = Query(..., min_length=2),
):
    """
    Isolated diagnostic endpoint for the Easycosmetic scraper.

    This does not modify or invoke the normal ScentHunter search flow.
    """
    return diagnose(q)


@router.get("/easycosmetic-search")
def debug_easycosmetic_search(
    q: str = Query(..., min_length=2),
):
    """
    Search-only diagnostic.

    Useful for proving that Easycosmetic search discovery works before
    product parsing is involved.
    """
    return {
        "diagnostic": True,
        "store": "Easycosmetic",
        "query": q,
        "candidates": search(q),
    }


@router.get("/easycosmetic-product")
def debug_easycosmetic_product(
    url: str = Query(..., min_length=10),
):
    """
    Parse one explicit Easycosmetic product URL.
    """
    product = parse_product(url)

    return {
        "diagnostic": True,
        "store": "Easycosmetic",
        "url": url,
        "product": product,
    }
