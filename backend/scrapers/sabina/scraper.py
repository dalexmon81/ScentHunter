# TEST DIAGNOSTICO 5
# Solo analisi: nessuna modifica allo scraper.
# Riceve la query direttamente da ScentHunter.

import re
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/it/",
}

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def scrape(query):
    query = clean(query)
    print(f"SABINA_TEST5 query_received: {query!r}")

    url = BASE + "/it/ricerca_old?s=" + quote_plus(query)
    print("SABINA_TEST5 request:", url)

    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        html = r.text
        print(
            "SABINA_TEST5 response:",
            f"status={r.status_code}",
            f"final_url={r.url}",
            f"bytes={len(r.content)}",
        )

        low = html.lower()

        # Mostriamo il contesto di OGNI occorrenza di liquid e brun.
        for term in ("liquid", "brun"):
            positions = [m.start() for m in re.finditer(re.escape(term), low)]
            print(f"SABINA_TEST5 {term}_occurrences:", len(positions))

            for i, pos in enumerate(positions[:30], 1):
                a = max(0, pos - 700)
                b = min(len(html), pos + 1400)
                ctx = clean(html[a:b])

                print(f"SABINA_TEST5 {term.upper()}_CONTEXT {i}")
                print(ctx[:2200])

        soup = BeautifulSoup(html, "html.parser")

        # Controlliamo tutti gli script che possono contenere dati di ricerca.
        print("SABINA_TEST5 scripts_total:", len(soup.find_all("script")))

        for i, script in enumerate(soup.find_all("script"), 1):
            txt = script.get_text(" ", strip=False)
            lowtxt = txt.lower()

            if any(x in lowtxt for x in ("search", "autocomplete", "suggest", "product", "ajax")):
                print(
                    f"SABINA_TEST5 RELEVANT_SCRIPT {i}: "
                    f"chars={len(txt)}"
                )
                print(clean(txt)[:3500])

        # Individuiamo form/input collegati alla ricerca.
        print("SABINA_TEST5 FORMS:", len(soup.find_all("form")))

        for i, form in enumerate(soup.find_all("form"), 1):
            txt = clean(form.get_text(" ", strip=True))
            attrs = " ".join(
                f"{k}={v}"
                for k, v in form.attrs.items()
                if k in ("id", "class", "action", "method", "name")
            )

            if re.search(r"search|ricerca|autocomplete|query", attrs + " " + txt, re.I):
                print(f"SABINA_TEST5 SEARCH_FORM {i}")
                print(" attrs:", attrs)
                print(" text:", txt[:1500])
                print(" html:", clean(str(form))[:5000])

        # Tutti gli input/search/autocomplete.
        for i, el in enumerate(
            soup.select("input, select, textarea, [role='searchbox']"), 1
        ):
            attrs = " ".join(
                f"{k}={v}"
                for k, v in el.attrs.items()
                if k in (
                    "id", "name", "type", "value", "placeholder",
                    "class", "data-url", "data-search-url",
                    "data-autocomplete", "data-action"
                )
            )

            if re.search(r"search|ricerca|autocomplete|query|suggest", attrs, re.I):
                print(f"SABINA_TEST5 SEARCH_INPUT {i}")
                print(attrs)

        print("SABINA_TEST5 END_DIAGNOSTIC")
        return []

    except Exception as e:
        print("SABINA_TEST5 ERROR:", type(e).__name__, str(e))
        return []

def search(query):
    return scrape(query)

def search_sabina(query):
    return scrape(query)
