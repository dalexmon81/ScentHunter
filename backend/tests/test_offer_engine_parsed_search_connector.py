import unittest

from backend.offer_engine.connectors.parsed_search import ParsedSearchConnector
from backend.offer_engine.contracts import Availability, Verification


class FakeScraper:
    BASE_URL = "https://www.parfum-zentrum.de"

    def __init__(self, result, page_overrides=None):
        self.result = result
        self.page_overrides = page_overrides or {}
        self.page_fetches = []
        self.page_queries = []

    def search_stream(self, query):
        return self.result

    def product_from_page(self, session, url, query=""):
        return self.extract_product_page(session, url, query)

    def extract_product_page(self, session, url, query="", **kwargs):
        self.page_fetches.append(url)
        self.page_queries.append(query)
        row = next(
            item for item in self.result.get("results", [])
            if item.get("url") == url
        )
        page = dict(row)
        page.update(self.page_overrides)
        page["attributes"] = {
            "size_ml": {"value": page.get("size_ml")},
            "concentration": {"value": page.get("concentration")},
        }
        page["identity"] = {
            "gtin": {"value": page.get("gtin")},
            "sku": {"value": page.get("sku")},
        }
        page["offer"] = {
            "price": page.get("price_num"),
            "currency": page.get("currency", "EUR"),
            "availability": page.get("availability"),
        }
        page["url"] = self.page_overrides.get("url", url)
        return page


class ParsedSearchConnectorTests(unittest.TestCase):
    def _row(self, **updates):
        row = {
            "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
            "brand": "French Avenue",
            "url": "https://www.parfum-zentrum.de/liquid-brun-100.html",
            "sku": "LB100",
            "gtin": "6298042001008",
            "size_ml": 100,
            "concentration": "Eau de Parfum",
            "price_num": 49.95,
            "currency": "EUR",
            "availability": "in_stock",
        }
        row.update(updates)
        return row

    def test_discovery_and_observation_preserve_variant_and_gtin(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success",
                "verified": True,
                "results": [self._row()],
                "details": {},
            }),
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        observation = connector.observe(listing)
        self.assertEqual(listing.external_id, "LB100")
        self.assertEqual(listing.raw_size_ml, 100)
        self.assertEqual(listing.raw_gtin, "6298042001008")
        self.assertEqual(listing.market, "DE")
        self.assertEqual(str(observation.price), "49.95")
        self.assertEqual(observation.availability, Availability.IN_STOCK)
        self.assertEqual(connector._scraper.page_fetches, [listing.product_url])
        self.assertEqual(connector._scraper.page_queries, ["Liquid Brun 100 ml"])
        self.assertEqual(observation.raw_payload["evidence_source"], "fetched_product_detail")
        self.assertEqual(observation.verification, Verification.UNVERIFIED)
        self.assertEqual(observation.raw_payload["parsed_page"]["attributes"]["size_ml"]["value"], 100)
        self.assertEqual(observation.raw_payload["parsed_page"]["identity"]["gtin"]["value"], "6298042001008")

    def test_search_snippet_price_is_ignored_in_favor_of_product_page_price(self):
        scraper = FakeScraper(
            {
                "status": "success", "verified": True,
                "results": [self._row(price_num=49.95)],
            },
            page_overrides={"price_num": 37.40},
        )
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=scraper,
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        observation = connector.observe(listing)
        self.assertEqual(str(observation.price), "37.4")
        self.assertEqual(scraper.page_fetches, [listing.product_url])

    def test_discovery_excludes_gift_bundles_containing_the_searched_perfume(self):
        product = self._row()
        bundle = self._row(
            name="Mystery Box Liquid Brun 2 by French Avenue Men Perfume Gift Set 300 ml",
            url="https://www.parfum-zentrum.de/mystery-box-liquid-brun-gift-set.html",
            size_ml=300,
            sku="BUNDLE-300",
        )
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [product, bundle],
            }),
        )
        listings = list(connector.discover("Liquid Brun"))
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].external_id, "LB100")

    def test_product_page_title_can_supply_missing_exact_size(self):
        scraper = FakeScraper({
            "status": "success", "verified": True,
            "results": [self._row(size_ml=None)],
        })
        connector = ParsedSearchConnector(
            "perfumemarket",
            "scrapers.perfumemarket.scraper",
            "NL",
            scraper=scraper,
        )
        listing = next(iter(connector.discover("Liquid Brun")))
        observation = connector.observe(listing)
        self.assertIsNone(listing.raw_size_ml)
        self.assertEqual(
            observation.raw_payload["parsed_page"]["attributes"]["size_ml"]["value"],
            100,
        )

    def test_sabina_selects_the_exact_variant_offer_not_parent_page_price(self):
        variant_url = "https://www.sabina.com/liquid-brun.html#/25-tama_o-100_ml"
        row = self._row(
            url=variant_url,
            sku="SAB-100",
            gtin="",
            price_num=89.99,
            size_ml=100,
        )
        scraper = FakeScraper(
            {"status": "success", "verified": True, "results": [row]},
            page_overrides={
                "variants": [
                    {
                        "size_ml": 100,
                        "price_num": 42.50,
                        "currency": "EUR",
                        "availability": "in_stock",
                        "sku": "SAB-100",
                        "url": variant_url,
                    },
                    {
                        "size_ml": 150,
                        "price_num": 59.90,
                        "currency": "EUR",
                        "availability": "in_stock",
                        "sku": "SAB-150",
                        "url": "https://www.sabina.com/liquid-brun.html#/26-tama_o-150_ml",
                    },
                ],
            },
        )
        scraper.BASE_URL = "https://www.sabina.com"
        connector = ParsedSearchConnector(
            "sabina",
            "scrapers.sabina.scraper",
            "ES",
            scraper=scraper,
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        observation = connector.observe(listing)
        self.assertEqual(str(observation.price), "42.5")
        self.assertEqual(observation.availability, Availability.IN_STOCK)
        self.assertEqual(observation.evidence_url, variant_url)

    def test_reused_product_sku_does_not_collapse_different_sizes(self):
        shared_url = "https://www.parfum-zentrum.de/liquid-brun.html"
        rows = [
            self._row(url=shared_url, size_ml=100),
            self._row(url=shared_url, size_ml=150),
        ]
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True, "results": rows,
            }),
        )
        listings = list(connector.discover("Liquid Brun"))
        self.assertEqual(len(listings), 2)
        self.assertEqual({item.raw_size_ml for item in listings}, {100, 150})
        self.assertEqual(len({item.external_id for item in listings}), 2)

    def test_product_page_redirect_to_another_path_is_rejected(self):
        scraper = FakeScraper(
            {
                "status": "success", "verified": True,
                "results": [self._row()],
            },
            page_overrides={"url": "https://www.parfum-zentrum.de/another-product.html"},
        )
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=scraper,
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        with self.assertRaisesRegex(RuntimeError, "redirected_to_different_product"):
            connector.observe(listing)

    def test_multi_item_gift_sets_are_not_treated_as_single_perfume_listings(self):
        row = self._row(
            name="French Avenue Liquid Brun Mystery Box Gift Set 300 ml",
            size_ml=300,
            sku="MYSTERY-BOX",
        )
        connector = ParsedSearchConnector(
            "orioudh", "scrapers.orioudh.scraper", "EU",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [row],
            }),
        )
        self.assertEqual(list(connector.discover("Liquid Brun")), [])

    def test_tracking_query_duplicates_are_removed_but_other_sizes_are_kept(self):
        first = self._row(
            url="https://www.parfum-zentrum.de/products/liquid-brun-100.html",
            sku="SHARED-SKU",
        )
        duplicate = self._row(
            url="https://www.parfum-zentrum.de/products/liquid-brun-100.html?_pos=1&_psq=Liquid+Brun&_ss=e",
            sku="SHARED-SKU",
        )
        sibling = self._row(
            name="French Avenue Liquid Brun Limited Edition 150 ml",
            url="https://www.parfum-zentrum.de/products/liquid-brun-150.html?_pos=2",
            sku="SHARED-SKU",
            gtin="6298042001831",
            size_ml=150,
        )
        connector = ParsedSearchConnector(
            "bplatz", "scrapers.bplatz.scraper", "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [first, duplicate, sibling],
            }),
        )
        listings = list(connector.discover("Liquid Brun"))
        self.assertEqual(len(listings), 2)
        self.assertEqual({item.raw_size_ml for item in listings}, {100, 150})

    def test_perfumemarket_locale_and_www_aliases_are_deduplicated(self):
        first = self._row(
            url="https://perfumemarket.nl/products/french-avenue-liquid-brun-men100ml-edp",
            sku="PM-LB100",
        )
        alias = self._row(
            url="https://www.perfumemarket.nl/nl/products/french-avenue-liquid-brun-men100ml-edp",
            sku="PM-LB100",
        )
        scraper = FakeScraper({
            "status": "success", "verified": True,
            "results": [first, alias],
        })
        scraper.BASE_URL = "https://perfumemarket.nl"
        connector = ParsedSearchConnector(
            "perfumemarket", "scrapers.perfumemarket.scraper", "NL",
            scraper=scraper,
        )
        listings = list(connector.discover("Liquid Brun"))
        self.assertEqual(len(listings), 1)

    def test_verified_partial_discovery_keeps_page_verified_candidates(self):
        connector = ParsedSearchConnector(
            "bplatz",
            "scrapers.bplatz.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "partial",
                "verified": True,
                "results": [self._row()],
                "details": {"discovery_errors": [{"source": "search_json", "status": "error"}]},
            }),
        )
        listing = next(iter(connector.discover("Liquid Brun 100 ml")))
        observation = connector.observe(listing)
        self.assertEqual(listing.external_id, "LB100")
        self.assertEqual(observation.availability, Availability.IN_STOCK)

    def test_sold_out_result_never_keeps_a_stale_price(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [self._row(availability="out_of_stock")],
            }),
        )
        listing = next(iter(connector.discover("Liquid Brun")))
        observation = connector.observe(listing)
        self.assertEqual(observation.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(observation.price)

    def test_unknown_stock_is_not_guessed_from_available_boolean(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [self._row(availability=None, available=True)],
            }),
        )
        listing = next(iter(connector.discover("Liquid Brun")))
        observation = connector.observe(listing)
        self.assertEqual(observation.availability, Availability.UNKNOWN)

    def test_discovery_challenge_fails_closed(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "unavailable", "verified": False, "results": [],
                "details": {"client_challenge": True},
            }),
        )
        with self.assertRaisesRegex(RuntimeError, "parfumzentrum_discovery_unavailable"):
            list(connector.discover("Liquid Brun"))

    def test_foreign_host_result_is_rejected(self):
        connector = ParsedSearchConnector(
            "parfumzentrum",
            "scrapers.parfumzentrum.scraper",
            "DE",
            scraper=FakeScraper({
                "status": "success", "verified": True,
                "results": [self._row(url="https://www.sabina.com/wrong-store.html")],
            }),
        )
        self.assertEqual(list(connector.discover("Liquid Brun")), [])


if __name__ == "__main__":
    unittest.main()
