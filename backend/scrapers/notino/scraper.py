import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "Notino"
BASE_URL = "https://www.notino.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

PRICE_RE = re.compile(
    r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€",
    re.I,
)

# Titoli generici di pagina/ricerca da scartare come nome prodotto
GENERIC_TITLES = [
    "résultat de la recherche",
    "nombre de produits",
    "recherche",
    "produits",
    "résultats",
    "page",
    "chargement",
    "loading",
]

# Testi che indicano chiaramente indisponibilità / niente vendita attuale
UNAVAILABLE_PATTERNS = [
    "rupture de stock",   # actuellement en rupture de stock
    "épuisé",             # produit épuisé
    "non disponible",     # non disponible
    "pas disponible",     # pas disponible
]


def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _words(s):
    return [
        x
        for x in re.findall(r"[a-z0-9]+", _clean(s).lower())
        if len(x) > 1
    ]


def _matches(text, query):
    text = _clean(text).lower()
    return all(word in text for word in _words(query))


def _is_generic_title(title):
    t = _clean(title).lower()
    return any(g in t for g in GENERIC_TITLES)
