"""ParfumCity universal adapter (legacy Shopify search already fetches variants)."""
from scrapers.parfumcity import scraper
from app.connectors.legacy_store import LegacyStoreConnector

class ParfumCityConnector(LegacyStoreConnector):
    def __init__(self, discovery_terms=(), *, search_func=None, page_loader=None):
        # ParfumCity.search() already returns fully parsed product/variant rows;
        # unlike the other Shopify adapters, this scraper has no public page parser.
        super().__init__("parfumcity", scraper,
            page_parser=None, discovery_terms=discovery_terms,
            search_func=search_func, page_loader=page_loader)
