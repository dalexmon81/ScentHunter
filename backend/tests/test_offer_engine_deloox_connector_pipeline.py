"""End-to-end Deloox connector contract tests against the reviewed catalog."""
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.offer_engine.connectors.deloox import DelooxConnector
from backend.offer_engine.contracts import Availability
from backend.offer_engine.policy import OfferPolicy
from backend.offer_engine.resolver import resolve_observation
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


URL_100 = "https://www.deloox.be/produit/1355229/french-avenue-liquid-brun-eau-de-parfum-100-ml.html"
URL_150 = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"


def page(url, title, size, availability, price, gtin=None):
    return {
        "url": url,
        "name": title,
        "brand": "French Avenue",
        "sku": url.split("/")[4],
        "gtin": gtin,
        "identity": {
            "sku": {"value": url.split("/")[4], "source": "jsonld"},
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
        },
        "attributes": {
            "size_ml": {"value": size, "source": "product_name_or_url"},
            "concentration": {"value": "Extrait de Parfum" if size == 150 else "Eau de Parfum"},
        },
        "offer": {"price": price, "currency": "EUR", "availability": availability},
        "raw_data": {"jsonld": {"gtin13": gtin} if gtin else {}},
    }


class DelooxConnectorPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
        cls.matcher = CanonicalMatcher(catalog)

    def _run(self, url, title, size, availability, price, gtin=None):
        parsed = page(url, title, size, availability, price, gtin)
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value={"status": "success", "verified": True, "results": [parsed], "details": {}}), \
             patch("backend.offer_engine.connectors.deloox.scraper.extract_product_page", return_value=parsed):
            connector = DelooxConnector(session=object())
            listing = next(iter(connector.discover("Liquid Brun")))
            observation = connector.observe(listing)

        resolved = resolve_observation(listing, observation, self.matcher)
        return listing, observation, resolved

    def test_discovery_challenge_is_reported_as_failure_not_empty_success(self):
        blocked = {
            "status": "unavailable",
            "verified": False,
            "results": [],
            "details": {"search_failure_reasons": {"client_challenge": 12}},
        }
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value=blocked):
            with self.assertRaisesRegex(RuntimeError, "deloox_discovery_unavailable"):
                list(DelooxConnector(session=object()).discover("Liquid Brun"))

    def test_discovery_rejects_unrelated_products_sharing_only_the_word_liquid(self):
        relevant = page(
            URL_100,
            "French Avenue Liquid Brun Eau de Parfum 100 ml",
            100, "in_stock", 39.99,
        )
        unrelated = [
            {
                **page(
                    "https://www.deloox.be/produit/1401316/pupa-im-sexy-liquid-lip-colour-006-strawberry-red-27-ml.html",
                    "Pupa I'm Sexy Liquid Lip Colour 006 Strawberry Red 27 ml",
                    27, "in_stock", 8.99,
                ),
                "brand": "Pupa",
            },
            {
                **page(
                    "https://www.deloox.be/produit/1347246/chanel-rouge-allure-liquid-55-ml.html",
                    "Chanel Rouge Allure Liquid 55 ml",
                    55, "in_stock", 39.99,
                ),
                "brand": "Chanel",
            },
        ]
        with patch(
            "backend.offer_engine.connectors.deloox.scraper.search_stream",
            return_value={
                "status": "success", "verified": True,
                "results": [*unrelated, relevant], "details": {},
            },
        ):
            listings = list(DelooxConnector(session=object()).discover("Liquid Brun"))
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].product_url, URL_100)

    def test_size_qualified_search_uses_parsed_size_when_title_omits_it(self):
        url = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-limited-edition.html"
        parsed = page(
            url,
            "French Avenue Liquid Brun Extrait de Parfum Limited Edition",
            150, "out_of_stock", None, "6298042001831",
        )
        with patch(
            "backend.offer_engine.connectors.deloox.scraper.search_stream",
            return_value={"status": "success", "verified": True, "results": [parsed], "details": {}},
        ):
            listings = list(DelooxConnector(session=object()).discover(
                "Liquid Brun Limited Edition 150 ml"
            ))
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].raw_size_ml, 150)
        self.assertEqual(listings[0].product_url, url)

    def test_150ml_limited_edition_keeps_out_of_stock_and_no_price(self):
        listing, raw, resolved = self._run(
            URL_150,
            "French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml",
            150, "out_of_stock", None, "6298042001831",
        )
        self.assertEqual(listing.raw_size_ml, 150)
        self.assertEqual(raw.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(raw.price)
        self.assertEqual(raw.verification.value, "unverified")
        self.assertEqual(raw.listing_key, "deloox:1385920")
        self.assertEqual(resolved.status, "matched")
        self.assertEqual(resolved.observation.product_id, "SH-0031")
        self.assertEqual(resolved.observation.variant_id, "VAR-f5aff76b4bb5de8a")
        self.assertTrue(OfferPolicy().evaluate(resolved.observation).publish)

    def test_market_and_evidence_url_follow_actual_storefront_locale(self):
        url = "https://www.deloox.nl/produit/1355229/french-avenue-liquid-brun-eau-de-parfum-100-ml.html"
        parsed = page(url, "French Avenue Liquid Brun Eau de Parfum 100 ml", 100, "in_stock", 49.95)
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value={"status": "success", "verified": True, "results": [parsed], "details": {}}), \
             patch("backend.offer_engine.connectors.deloox.scraper.extract_product_page", return_value=parsed):
            connector = DelooxConnector(session=object())
            listing = next(iter(connector.discover("Liquid Brun")))
            observation = connector.observe(listing)
        self.assertEqual(listing.market, "NL")
        self.assertEqual(observation.evidence_url, url)

    def test_spain_storefront_is_recorded_as_es_market(self):
        url = "https://www.deloox.es/produit/1355229/french-avenue-liquid-brun-eau-de-parfum-100-ml.html"
        parsed = page(url, "French Avenue Liquid Brun Eau de Parfum 100 ml", 100, "in_stock", 49.95)
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value={"status": "success", "verified": True, "results": [parsed], "details": {}}), \
             patch("backend.offer_engine.connectors.deloox.scraper.extract_product_page", return_value=parsed):
            connector = DelooxConnector(session=object())
            listing = next(iter(connector.discover("Liquid Brun")))
            observation = connector.observe(listing)
        self.assertEqual(listing.market, "ES")
        self.assertEqual(observation.evidence_url, url)

    def test_cross_market_redirect_is_rejected(self):
        be_url = URL_100
        nl_url = URL_100.replace(".deloox.be", ".deloox.nl")
        discovered = page(be_url, "French Avenue Liquid Brun Eau de Parfum 100 ml", 100, "in_stock", 49.95)
        redirected = page(nl_url, "French Avenue Liquid Brun Eau de Parfum 100 ml", 100, "in_stock", 49.95)
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value={"status": "success", "verified": True, "results": [discovered], "details": {}}), \
             patch("backend.offer_engine.connectors.deloox.scraper.extract_product_page", return_value=redirected):
            connector = DelooxConnector(session=object())
            listing = next(iter(connector.discover("Liquid Brun")))
            with self.assertRaisesRegex(ValueError, "market_changed_since_discovery"):
                connector.observe(listing)

    def test_100ml_standard_is_not_collapsed_into_150ml_limited_edition(self):
        listing, raw, resolved = self._run(
            URL_100,
            "French Avenue Liquid Brun Eau de Parfum 100 ml",
            100, "in_stock", 49.95,
        )
        self.assertEqual(listing.raw_size_ml, 100)
        self.assertEqual(raw.price, Decimal("49.95"))
        self.assertEqual(resolved.status, "matched")
        self.assertEqual(resolved.observation.product_id, "SH-0030")
        self.assertEqual(resolved.observation.variant_id, "VAR-f87146c82d167f4c")
        self.assertNotEqual(resolved.observation.variant_id, "VAR-f5aff76b4bb5de8a")


    def test_spanish_product_route_is_rejected_on_belgian_storefront(self):
        spanish_route = "https://www.deloox.be/producto/1205999/dior-sauvage-parfum-perfume-60-ml.html"
        parsed = page(spanish_route, "Dior Sauvage Parfum 60 ml", 60, "in_stock", 69.95)
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value={
            "status": "success", "verified": True, "results": [parsed], "details": {}
        }):
            listings = list(DelooxConnector(session=object()).discover("Sauvage"))
        self.assertEqual(listings, [])

    def test_spanish_product_route_is_allowed_on_spanish_storefront(self):
        spanish_route = "https://www.deloox.es/producto/1205999/dior-sauvage-parfum-perfume-60-ml.html"
        parsed = page(spanish_route, "Dior Sauvage Parfum 60 ml", 60, "in_stock", 69.95)
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value={
            "status": "success", "verified": True, "results": [parsed], "details": {}
        }), patch("backend.offer_engine.connectors.deloox.scraper.extract_product_page", return_value=parsed):
            connector = DelooxConnector(session=object())
            listings = list(connector.discover("Sauvage"))
            observation = connector.observe(listings[0])
        self.assertEqual(listings[0].market, "ES")
        self.assertEqual(observation.evidence_url, spanish_route)



    def test_connector_records_explicit_sold_out_when_page_parser_reports_it(self):
        parsed = page(
            URL_150,
            "French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml",
            150, "out_of_stock", None, "6298042001831",
        )
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value={
            "status": "success", "verified": True, "results": [parsed], "details": {},
        }), patch("backend.offer_engine.connectors.deloox.scraper.extract_product_page", return_value=parsed):
            connector = DelooxConnector(session=object())
            listing = next(iter(connector.discover("Liquid Brun")))
            observation = connector.observe(listing)
        self.assertEqual(observation.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(observation.price)

    def test_connector_preserves_in_stock_price_from_verified_parser_contract(self):
        parsed = page(
            URL_100,
            "French Avenue Liquid Brun Eau de Parfum 100 ml",
            100, "in_stock", 49.95,
        )
        with patch("backend.offer_engine.connectors.deloox.scraper.search_stream", return_value={
            "status": "success", "verified": True, "results": [parsed], "details": {},
        }), patch("backend.offer_engine.connectors.deloox.scraper.extract_product_page", return_value=parsed):
            connector = DelooxConnector(session=object())
            listing = next(iter(connector.discover("Liquid Brun")))
            observation = connector.observe(listing)
        self.assertEqual(observation.availability, Availability.IN_STOCK)
        self.assertEqual(observation.price, Decimal("49.95"))


    def test_same_market_redirect_to_another_product_path_is_rejected(self):
        discovered = page(
            URL_100,
            "French Avenue Liquid Brun Eau de Parfum 100 ml",
            100, "in_stock", 49.95,
        )
        redirected_url = "https://www.deloox.be/produit/9999999/another-liquid-brun-100-ml.html"
        redirected = page(
            redirected_url,
            "French Avenue Liquid Brun Eau de Parfum 100 ml",
            100, "in_stock", 49.95,
        )
        with patch(
            "backend.offer_engine.connectors.deloox.scraper.search_stream",
            return_value={"status": "success", "verified": True, "results": [discovered], "details": {}},
        ), patch(
            "backend.offer_engine.connectors.deloox.scraper.extract_product_page",
            return_value=redirected,
        ):
            connector = DelooxConnector(session=object())
            listing = next(iter(connector.discover("Liquid Brun")))
            with self.assertRaisesRegex(ValueError, "redirected_to_different_product"):
                connector.observe(listing)


    def test_discovery_preserves_same_sku_for_distinct_sizes_as_distinct_listings(self):
        base = page(
            URL_100,
            "French Avenue Liquid Brun Eau de Parfum 100 ml",
            100, "in_stock", 49.95,
        )
        sibling_url = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        sibling = page(
            sibling_url,
            "French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml",
            150, "out_of_stock", None, "6298042001831",
        )
        # Simulate a retailer that reuses one product-level SKU across sizes.
        sibling["sku"] = base["sku"]
        sibling["identity"]["sku"] = base["identity"]["sku"]
        with patch(
            "backend.offer_engine.connectors.deloox.scraper.search_stream",
            return_value={"status": "success", "verified": True, "results": [base, sibling], "details": {}},
        ):
            listings = list(DelooxConnector(session=object()).discover("Liquid Brun"))
        self.assertEqual({item.raw_size_ml for item in listings}, {100, 150})
        self.assertEqual(len({item.external_id for item in listings}), 2)
        self.assertEqual(len({item.product_url for item in listings}), 2)


    def test_discovery_preserves_two_distinct_deloox_urls_with_shared_sku(self):
        first = page(
            URL_100,
            "French Avenue Liquid Brun Eau de Parfum 100 ml",
            100, "in_stock", 49.95,
        )
        second_url = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        second = page(
            second_url,
            "French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml",
            150, "out_of_stock", None, "6298042001831",
        )
        second["sku"] = first["sku"]
        second["identity"]["sku"] = first["identity"]["sku"]
        with patch(
            "backend.offer_engine.connectors.deloox.scraper.search_stream",
            return_value={"status": "success", "verified": True, "results": [first, second], "details": {}},
        ):
            listings = list(DelooxConnector(session=object()).discover("Liquid Brun"))
        self.assertEqual({item.raw_size_ml for item in listings}, {100, 150})
        self.assertEqual(len({item.external_id for item in listings}), 2)
        self.assertEqual(len({item.product_url for item in listings}), 2)

if __name__ == "__main__":
    unittest.main()
