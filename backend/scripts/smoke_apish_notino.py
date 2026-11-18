"""One bounded, read-only API.SH Notino provider smoke test for the isolated Fly pilot."""
from __future__ import annotations

import json

from scrapers.notino.scraper import _search_apish


def main() -> int:
    rows, diagnostics = _search_apish("French Avenue Liquid Brun 100 ml")
    safe = {
        key: value
        for key, value in diagnostics.items()
        if key.lower() not in {"api_key", "token", "authorization"}
    }
    print("APISH_DIAGNOSTICS=" + json.dumps(safe, ensure_ascii=False, sort_keys=True))
    print("APISH_VERIFIED_OFFERS=" + str(len(rows)))
    if not diagnostics.get("configured"):
        raise SystemExit("APISH_API_KEY is not configured in the isolated pilot.")
    if diagnostics.get("error"):
        raise SystemExit("API.SH provider request failed: " + str(diagnostics["error"]))
    print("APISH_PROVIDER_REQUEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
