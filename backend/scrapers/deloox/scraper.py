import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = BASE_URL + "/en"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


PRICE_RE = re.compile(
    r"""
    (?:
        €\s*
        (?P<euro_before>\d{1,4})
        \s*
        (?:[,.\^]\s*)+
        (?P<cents_before>\d{2})
        \s*\^*

        |

        (?P<euro_after>\d{1,4})
        \s*
        (?:[,.\^]\s*)+
        (?P<cents_after>\d{2})
        \s*\^*
        \s*€

        |

        €\s*(?P<integer_before>\d{1,4})(?![\d.,])

        |

        (?P<integer_after>\d{1,4})
        \s*€
    )
    """,
    re.I | re.X,
)


SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
    "currently unavailable",
)

NON_FRAGRANCE = (
    "body mist",
    "body spray",
    "body lotion",
    "body cream",
    "body oil",
    "body wash",
    "shower gel",
    "shower oil",
    "hand and body",
    "hand cream",
    "deodorant",
    "after shave",
    "aftershave",
    "hair mist",
    "hair spray",
    "soap",
)

SIZE_RE = re.compile(
    r"\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b",
    re.I,
)

SIZE_FULL_RE = re.compile(
    r"^(\d{1,3}(?:[.,]\d+)?)\s*ml$",
    re.I,
)


CATEGORY_FALLBACKS = (
    (
        ("jean", "paul", "gaultier"),
        "https://www.deloox.com/category/"
        "1072906/jean-paul-gaultier-fragrances.html",
    ),
    (
        ("le", "beau", "le", "parfum"),
        "https://www.deloox.com/category/"
        "1053446/le-beau.html",
    ),
    (
        ("miu", "miu"),
        "https://www.deloox.com/category/"
        "1071574/miu-miu-fragrances.html",
    ),
)


NON_FRAGRANCE_TOKENS = {
    tuple(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            value.lower(),
        ).split()
    )
    for value in NON_FRAGRANCE
}


def _clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def _norm(value):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        _clean(value).lower(),
    ).strip()


def _tokens(value):
    return [
        token
        for token in _norm(value).split()
        if len(token) > 1
