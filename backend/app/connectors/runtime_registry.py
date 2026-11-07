"""Runtime construction for the ten registered store connectors.

Discovery terms are supplied as JSON in SCENTHUNTER_DISCOVERY_TERMS_JSON,
for example {"deloox":["Dior Sauvage 100 ml"],"sabina":["Chanel No 5"]}.
No live discovery is attempted for a store without configured terms, except
Notino where the authorized affiliate feed is its discovery source.
"""
from __future__ import annotations

import json
import os
from typing import Any

from app.connectors import (
    BplatzConnector, DelooxConnector, EasycosmeticConnector,
    NotinoAffiliateFeedConnector, OrioudhConnector, ParfumCityConnector, PerfumesMemConnector,
    PerfumeMarketConnector, ParfumzentrumConnector, SabinaConnector,
)

def _terms() -> dict[str, list[str]]:
    raw = os.environ.get("SCENTHUNTER_DISCOVERY_TERMS_JSON", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SCENTHUNTER_DISCOVERY_TERMS_JSON must be valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("SCENTHUNTER_DISCOVERY_TERMS_JSON must be an object")
    return {
        str(key): [str(term).strip() for term in terms if str(term).strip()]
        for key, terms in value.items()
        if isinstance(terms, list)
    }

def build_connectors() -> dict[str, Any]:
    terms = _terms()
    return {
        "notino": NotinoAffiliateFeedConnector(),
        "deloox": DelooxConnector(terms.get("deloox", ())),
        "easycosmetic": EasycosmeticConnector(terms.get("easycosmetic", ())),
        "sabina": SabinaConnector(terms.get("sabina", ())),
        "parfumzentrum": ParfumzentrumConnector(terms.get("parfumzentrum", ())),
        "perfumemarket": PerfumeMarketConnector(terms.get("perfumemarket", ())),
        "parfumcity": ParfumCityConnector(terms.get("parfumcity", ())),
        "bplatz": BplatzConnector(terms.get("bplatz", ())),
        "orioudh": OrioudhConnector(terms.get("orioudh", ())),
        # Published terms prohibit crawling/extraction and commercial reuse;
        # this connector remains fail-closed until written permission is recorded.
        "perfumesmem": PerfumesMemConnector(),
    }

def get_connector(store_key: str):
    connectors = build_connectors()
    try:
        return connectors[store_key]
    except KeyError:
        raise ValueError(f"unknown_store_connector:{store_key}") from None
