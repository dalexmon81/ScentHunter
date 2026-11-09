"""Official Maison Alhambra detail-page evidence for twelve existing identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Afro Leather": ("https://maisonalhambra-usa.com/products/maison-alhambra-afro-leather-eau-de-parfum-for-everyone", 80, "SHV-SH-MAISON-ALHAMBRA-29189f4e-80-000", "6291108736081"),
    "Alpine Homme Sport": ("https://maisonalhambra-usa.com/products/maison-alhambra-alpine-homme-sport-eau-de-parfum-for-men", 100, "SHV-SH-MAISON-ALHAMBRA-0840cbf0-100-000", "6291108735879"),
    "Anarch": ("https://maisonalhambra-usa.com/products/maison-alhambra-anarch-eau-de-parfum-for-everyone", 100, "SHV-SH-MAISON-ALHAMBRA-61a3375c-100-000", "6291107459080"),
    "Anchor Black": ("https://maisonalhambra-usa.com/products/maison-alhambra-anchor-black-eau-de-parfum-for-men", 100, "SHV-SH-MAISON-ALHAMBRA-482df3c5-100-000", "6291108730058"),
    "Aromatic Rouge": ("https://maisonalhambra-usa.com/products/maison-alhambra-aromatic-rouge-eau-de-parfum-for-women", 100, "SHV-SH-MAISON-ALHAMBRA-ebdf4fbf-100-000", "6291107459097"),
    "Athena": ("https://maisonalhambra-usa.com/products/maison-alhambra-athena-eau-de-parfum-for-women", 100, "SHV-SH-MAISON-ALHAMBRA-2fc0bad4-100-000", "6290360599243"),
    "Aura D'Eclat": ("https://maisonalhambra-usa.com/products/maison-alhambra-aura-declat-eau-de-parfum-for-women", 100, "SHV-SH-MAISON-ALHAMBRA-7c1ece5a-100-000", "6291107459103"),
    "Avant Ruby": ("https://maisonalhambra-usa.com/products/maison-alhambra-avant-ruby-eau-de-parfum-for-women", 100, "SHV-SH-MAISON-ALHAMBRA-f80b4af7-100-000", "6290362343134"),
    "Avant Silk": ("https://maisonalhambra-usa.com/products/maison-alhambra-avant-silk-eau-de-parfum-for-everyone", 100, "SHV-SH-MAISON-ALHAMBRA-1bc577a6-100-000", "6290362340768"),
    "Baroque Satin Oud": ("https://maisonalhambra-usa.com/products/maison-alhambra-baroque-satin-oud-eau-de-parfum-for-everyone", 100, "SHV-SH-MAISON-ALHAMBRA-b9e265b9-100-000", "6291108736050"),
    "Berlinetta": ("https://maisonalhambra-usa.com/products/maison-alhambra-berlinetta-eau-de-parfum-for-everyone", 100, "SHV-SH-MAISON-ALHAMBRA-0da920d5-100-000", "6291107459158"),
    "Black Origami": ("https://maisonalhambra-usa.com/products/maison-alhambra-black-origami-eau-de-parfum-for-everyone", 100, "SHV-SH-MAISON-ALHAMBRA-e3d1182c-100-000", "6291108730065"),
}


class MaisonAlhambraTwelveOfficialDetailsTests(unittest.TestCase):
    def test_existing_identities_have_official_pages_and_one_size_specific_variant(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "maison_alhambra_catalog")
        for name, (url, size, variant_id, gtin) in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in CATALOG["products"] if p.get("brand_name") == "Maison Alhambra" and p.get("canonical_name") == name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [size])
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), variant_id)
                self.assertEqual(variants[0].get("size_ml"), size)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)
                if gtin:
                    self.assertEqual(variants[0].get("gtin"), gtin)
                family_rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0].get("formats_ml"), [size])


if __name__ == "__main__":
    unittest.main()
