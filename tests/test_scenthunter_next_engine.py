"""Focused regression tests for the isolated ScentHunter next-engine foundation.

Run from the repository root with: python -m unittest discover -s tests -p "test_scenthunter_next_engine.py"
These tests do not access production services or write to the canonical catalog.
"""
import json
import tempfile
import unittest
from pathlib import Path

from backend.scenthunter_next_engine.catalog_repository import CatalogRepository, CatalogFormatError
from backend.scenthunter_next_engine.models import MatchStatus, OfferMatch, RetailerOffer
from backend.scenthunter_next_engine.offer_normalizer import normalize_offer, normalize_offers


class OfferNormalizerTests(unittest.TestCase):
    def test_normalizes_known_fields_and_keeps_original_payload(self):
        source = {
            "title": "Example Eau de Parfum",
            "brandName": "Example Brand",
            "sizeMl": 100,
            "currentPrice": "49.90",
            "productUrl": "https://shop.example/product/1",
            "imageUrl": "https://shop.example/image.jpg",
            "inStock": True,
        }
        offer = normalize_offer(source, retailer="Example Shop")
        self.assertEqual(offer.retailer, "Example Shop")
        self.assertEqual(offer.raw_name, "Example Eau de Parfum")
        self.assertEqual(offer.brand_raw, "Example Brand")
        self.assertEqual(offer.size_ml, 100)
        self.assertEqual(str(offer.price), "49.90")
        self.assertEqual(offer.availability, "in_stock")
        self.assertEqual(offer.raw_payload, source)

    def test_rejects_missing_product_name(self):
        with self.assertRaisesRegex(ValueError, "no recognized product-name"):
            normalize_offer({"price": 20}, retailer="Example Shop")

    def test_ignores_invalid_size_price_and_non_http_urls(self):
        offer = normalize_offer(
            {
                "name": "Example",
                "size_ml": "100.5",
                "price": "€49,90",
                "url": "javascript:alert(1)",
                "image_url": "not-a-url",
            },
            retailer="Example Shop",
        )
        self.assertIsNone(offer.size_ml)
        self.assertIsNone(offer.price)
        self.assertIsNone(offer.product_url)
        self.assertIsNone(offer.retailer_image_url)

    def test_batch_reports_rejected_rows_instead_of_silently_dropping_them(self):
        offers, rejected = normalize_offers(
            [{"name": "Valid"}, {"price": 5}, None],
            retailer="Example Shop",
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual([row["index"] for row in rejected], [1, 2])


class CanonicalCatalogTests(unittest.TestCase):
    def _catalog_file(self, data):
        temporary = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        with temporary:
            json.dump(data, temporary)
        self.addCleanup(lambda: Path(temporary.name).unlink(missing_ok=True))
        return temporary.name

    def test_links_only_explicit_variants_to_their_canonical_product(self):
        path = self._catalog_file(
            {
                "products": [
                    {
                        "product_id": "P-1",
                        "brand_name": "Brand",
                        "canonical_name": "Fragrance",
                        "canonical_image": "https://catalog.example/image.jpg",
                    }
                ],
                "variants": [
                    {
                        "variant_id": "V-100",
                        "product_id": "P-1",
                        "size_ml": 100,
                        "aliases": ["100 ml"],
                    },
                    {
                        "variant_id": "V-ORPHAN",
                        "product_id": "MISSING",
                        "size_ml": 50,
                    },
                ],
            }
        )
        catalog = CatalogRepository.from_file(path)
        product = catalog.get("P-1")
        self.assertIsNotNone(product)
        self.assertEqual(product.canonical_image_url, "https://catalog.example/image.jpg")
        self.assertEqual(len(product.variants), 1)
        self.assertEqual(product.variants[0].variant_id, "V-100")
        self.assertEqual(product.variants[0].size_ml, 100)
        self.assertEqual(catalog.source_variant_count(), 2)
        self.assertEqual(catalog.variant_count(), 1)
        self.assertEqual(catalog.skipped_variant_count(), 1)

    def test_rejects_duplicate_canonical_product_ids(self):
        path = self._catalog_file(
            {
                "products": [
                    {"product_id": "P-1", "brand_name": "Brand", "canonical_name": "One"},
                    {"product_id": "P-1", "brand_name": "Brand", "canonical_name": "Two"},
                ],
                "variants": [],
            }
        )
        with self.assertRaisesRegex(CatalogFormatError, "Duplicate canonical product ID"):
            CatalogRepository.from_file(path)


class MatchContractTests(unittest.TestCase):
    def test_matched_result_requires_real_canonical_product_and_variant_ids(self):
        offer = RetailerOffer(retailer="Shop", raw_name="Fragrance")
        with self.assertRaises(ValueError):
            OfferMatch(offer=offer, status=MatchStatus.MATCHED, canonical_product_id="P-1")

    def test_unresolved_result_cannot_expose_canonical_ids(self):
        offer = RetailerOffer(retailer="Shop", raw_name="Fragrance")
        with self.assertRaises(ValueError):
            OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                canonical_product_id="P-1",
            )


if __name__ == "__main__":
    unittest.main()
