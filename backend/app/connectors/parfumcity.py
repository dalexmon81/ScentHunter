"""ParfumCity universal adapter (Shopify product JSON parser)."""
from scrapers.parfumcity import scraper
from app.connectors.legacy_store import LegacyStoreConnector

class ParfumCityConnector(LegacyStoreConnector):
    def __init__(self, discovery_terms=(), *, search_func=None, page_loader=None):
        super().__init__("parfumcity", scraper,
            page_parser=scraper.extract_product_page,
            discovery_terms=discovery_terms, search_func=search_func,
            page_loader=page_loader)
