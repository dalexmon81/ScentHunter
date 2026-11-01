import unittest
from decimal import Decimal
from unittest.mock import patch

from backend.offer_engine.connectors.amazon_creators import AmazonCreatorsConnector
from backend.offer_engine.contracts import Availability


class AmazonCreatorsConnectorTests(unittest.TestCase):
    def _report(self, market="de"):
        return {
            "status": "success",
            "verified": True,
            "details": {"source": "amazon_creators_api", "candidate_count": 1},
            "results": [{
                "store": f"amazon_{market}",
                "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
                "brand": "French Avenue",
                "url": f"https://www.amazon.{market}/dp/B0D8L92LQW",
                "size_ml": 100,
                "concentration": "Eau de Parfum",
                "price_num": 29.99,
                "currency": "EUR",
            }],
        }

    def test_discovery_and_observation_use_exact_asin_live_get_items(self):
        connector = AmazonCreatorsConnector("de")
        with patch("backend.offer_engine.connectors.amazon_creators.amazon_creators_api.is_configured", return_value=True), \
             patch.object(connector._scraper, "search", return_value=self._report("de")), \
             patch("backend.offer_engine.connectors.amazon_creators.amazon_creators_api.get_product", return_value={
                 "url": "https://www.amazon.de/dp/B0D8L92LQW?tag=approved",
                 "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
                 "brand": "French Avenue",
                 "size_ml": 100,
                 "concentration": "Eau de Parfum",
                 "price_num": 28.50,
                 "currency": "EUR",
                 "availability": "in_stock",
                 "available": True,
             }) as get_product:
            listing = connector.discover("French Avenue Liquid Brun 100 ml")[0]
            observation = connector.observe(listing)

        self.assertEqual(listing.external_id, "B0D8L92LQW")
        self.assertEqual(listing.market, "DE")
        self.assertEqual(observation.price, Decimal("28.5"))
        self.assertEqual(observation.availability, Availability.IN_STOCK)
        self.assertEqual(observation.source, "amazon_creators_api")
        get_product.assert_called_once()

    def test_search_snippet_source_is_never_admitted(self):
        connector = AmazonCreatorsConnector("fr")
        report = self._report("fr")
        report["details"]["source"] = "bing_rss_public_index"
        with patch("backend.offer_engine.connectors.amazon_creators.amazon_creators_api.is_configured", return_value=True), \
             patch.object(connector._scraper, "search", return_value=report):
            with self.assertRaisesRegex(RuntimeError, "creators_discovery"):
                connector.discover("French Avenue Liquid Brun")

    def test_changed_variant_size_is_rejected(self):
        connector = AmazonCreatorsConnector("de")
        with patch("backend.offer_engine.connectors.amazon_creators.amazon_creators_api.is_configured", return_value=True), \
             patch.object(connector._scraper, "search", return_value=self._report("de")), \
             patch("backend.offer_engine.connectors.amazon_creators.amazon_creators_api.get_product", return_value={
                 "url": "https://www.amazon.de/dp/B0D8L92LQW",
                 "name": "French Avenue Liquid Brun Eau de Parfum 150 ml",
                 "size_ml": 150, "price_num": 28.50, "currency": "EUR", "available": True,
             }):
            listing = connector.discover("French Avenue Liquid Brun 100 ml")[0]
            with self.assertRaisesRegex(ValueError, "size_changed"):
                connector.observe(listing)


if __name__ == "__main__":
    unittest.main()
