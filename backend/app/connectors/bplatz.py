"""Bplatz universal adapter (Shopify JSON-LD product parser)."""
from scrapers.bplatz import scraper
from app.connectors.legacy_store import LegacyStoreConnector

class BplatzConnector(LegacyStoreConnector):
    def __init__(self, discovery_terms=(), *, search_func=None, page_loader=None):
        super().__init__("bplatz", scraper,
            page_parser=scraper.product_from_page,
            discovery_terms=discovery_terms, search_func=search_func,
            page_loader=page_loader)
