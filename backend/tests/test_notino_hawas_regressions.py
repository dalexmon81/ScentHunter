"""Regression coverage for exact Notino detail URLs and Hawas product separation."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base
from app.services.notino_affiliate import is_valid_notino_affiliate_url
from app.services.notino_feed_listings import refresh_notino_listings
from app.services.notino_phase2_search import search_notino_retailer_listings
from scrapers.notino.affiliate_feed import _product_url


def affiliate(destination: str) -> str:
    from urllib.parse import quote
    return "https://www.kqzyfj.com/click-123-456?url=" + quote(destination, safe="")


def row(external_id: str, title: str, destination: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": external_id,
        "brand": "Rasasi",
        "title": title,
        "link": affiliate(destination),
        "last_updated": now,
        "availability": "in stock",
        "price": "29.90 EUR",
        "size": "100 ml",
    }


class NotinoHawasRegressionTests(unittest.TestCase):
    def test_affiliate_clickout_must_resolve_to_a_notino_product_detail(self):
        self.assertTrue(is_valid_notino_affiliate_url(affiliate(
            "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/"
        )))
        self.assertFalse(is_valid_notino_affiliate_url(affiliate(
            "https://www.notino.fr/rasasi/hawas-ice/"
        )))
        self.assertFalse(is_valid_notino_affiliate_url(affiliate(
            "https://www.notino.fr/search/?q=hawas+ice"
        )))

    def test_cj_parser_rejects_generic_hawas_ice_page(self):
        self.assertEqual(
            _product_url("https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/"),
            "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/",
        )
        self.assertIsNone(_product_url("https://www.notino.fr/rasasi/hawas-ice/"))

    def test_hawas_ice_single_and_gift_set_are_not_mixed(self):
        single = affiliate(
            "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/"
        )
        gift = affiliate(
            "https://www.notino.fr/rasasi/hawas-ice-coffret-cadeau-pour-homme/p-17770001/"
        )
        self.assertTrue(is_valid_notino_affiliate_url(single))
        self.assertTrue(is_valid_notino_affiliate_url(gift))
        # The URL validator establishes a product-detail destination; the
        # existing bundle guard must still reject gift sets from perfume cards.
        from product_matcher import ProductMatcher
        self.assertTrue(ProductMatcher._is_non_fragrance_offer({
            "name": "Rasasi Hawas Ice",
            "brand": "Rasasi",
            "url": gift,
        }))
        self.assertFalse(ProductMatcher._is_non_fragrance_offer({
            "name": "Rasasi Hawas Ice Eau de Parfum 100 ml",
            "brand": "Rasasi",
            "url": single,
        }))

    def test_hawas_line_editions_remain_separate_retailer_listings(self):
        rows = [
            row("HAWAS-ICE", "Hawas Ice Eau de Parfum 100 ml",
                "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/"),
            row("HAWAS-ELIXIR", "Hawas Elixir Eau de Parfum 100 ml",
                "https://www.notino.fr/rasasi/hawas-elixir-eau-de-parfum/p-17770002/"),
            row("HAWAS-LA-MER", "Hawas La Mer Eau de Parfum 100 ml",
                "https://www.notino.fr/rasasi/hawas-la-mer-eau-de-parfum/p-17770003/"),
            row("HAWAS-MAJESTIC", "Hawas Majestic Eau de Parfum 100 ml",
                "https://www.notino.fr/rasasi/hawas-majestic-eau-de-parfum/p-17770004/"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notino.sqlite"
            engine = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(engine)
            now = datetime.now(timezone.utc)
            with Session(engine) as session, session.begin():
                result = refresh_notino_listings(session, rows, now)
                self.assertEqual(result["listings"], 4)
            with patch.dict("os.environ", {"NOTINO_PHASE2_DATABASE": str(path)}):
                found = search_notino_retailer_listings("Rasasi Hawas", set())
            self.assertEqual({item["external_id"] for item in found}, {
                "HAWAS-ICE", "HAWAS-ELIXIR", "HAWAS-LA-MER", "HAWAS-MAJESTIC",
            })
            self.assertEqual(len({item["url"] for item in found}), 4)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
