"""Twelve additional Maison Alhambra official-store identities and variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Dominate Absolu": ("SH-MAISON-ALHAMBRA-DOMINATE-ABSOLU", "https://lattafaparfum.eu/de-de/products/dominate-absolu", 100, "SHV-SH-MAISON-ALHAMBRA-DOMINATE-ABSOLU-100-000"),
    "La Rouge Baroque Extreme": ("SH-MAISON-ALHAMBRA-LA-ROUGE-BAROQUE-EXTREME", "https://lattafaparfum.eu/de-de/products/la-rouge-baroque-extreme", 100, "SHV-SH-MAISON-ALHAMBRA-LA-ROUGE-BAROQUE-EXTREME-100-000"),
    "La Rouge Baroque": ("SH-MAISON-ALHAMBRA-LA-ROUGE-BAROQUE", "https://lattafaparfum.eu/de-de/products/la-rouge-baroque", 100, "SHV-SH-MAISON-ALHAMBRA-LA-ROUGE-BAROQUE-100-000"),
    "Salvo": ("SH-MAISON-ALHAMBRA-SALVO", "https://lattafaparfum.eu/de-de/products/salvo", 100, "SHV-SH-MAISON-ALHAMBRA-SALVO-100-000"),
    "Sugar Me Marshmallow Dream": ("SH-MAISON-ALHAMBRA-SUGAR-ME-MARSHMALLOW-DREAM", "https://lattafaparfum.eu/de-de/products/sugar-me-marshmallow-dream", 100, "SHV-SH-MAISON-ALHAMBRA-SUGAR-ME-MARSHMALLOW-DREAM-100-000"),
    "Jean Lowe Maitre": ("SH-MAISON-ALHAMBRA-JEAN-LOWE-MAITRE", "https://lattafaparfum.eu/de-de/products/jean-lowe-maitre", 100, "SHV-SH-MAISON-ALHAMBRA-JEAN-LOWE-MAITRE-100-000"),
    "Sugar Me Dulce De Leche": ("SH-MAISON-ALHAMBRA-SUGAR-ME-DULCE-DE-LECHE", "https://lattafaparfum.eu/de-de/products/sugar-me-dulce-de-leche", 100, "SHV-SH-MAISON-ALHAMBRA-SUGAR-ME-DULCE-DE-LECHE-100-000"),
    "Kismet Magic": ("SH-MAISON-ALHAMBRA-KISMET-MAGIC", "https://lattafaparfum.eu/de-de/products/kismet-magic", 100, "SHV-SH-MAISON-ALHAMBRA-KISMET-MAGIC-100-000"),
    "Sugar Me Carrot Cake": ("SH-MAISON-ALHAMBRA-SUGAR-ME-CARROT-CAKE", "https://lattafaparfum.eu/de-de/products/sugar-me-carrot-cake", 100, "SHV-SH-MAISON-ALHAMBRA-SUGAR-ME-CARROT-CAKE-100-000"),
    "Unknown Deep Woods": ("SH-MAISON-ALHAMBRA-UNKNOWN-DEEP-WOODS", "https://lattafaparfum.eu/de-de/products/unknown-deep-woods", 100, "SHV-SH-MAISON-ALHAMBRA-UNKNOWN-DEEP-WOODS-100-000"),
    "Sugar Me Pistachio Chocolate": ("SH-MAISON-ALHAMBRA-SUGAR-ME-PISTACHIO-CHOCOLATE", "https://lattafaparfum.eu/de-de/products/sugar-me-pistachio-chocolate", 100, "SHV-SH-MAISON-ALHAMBRA-SUGAR-ME-PISTACHIO-CHOCOLATE-100-000"),
    "Sugar Me Creme Brulee": ("SH-MAISON-ALHAMBRA-SUGAR-ME-CREME-BRULEE", "https://lattafaparfum.eu/de-de/products/sugar-me-creme-brulee", 100, "SHV-SH-MAISON-ALHAMBRA-SUGAR-ME-CREME-BRULEE-100-000"),
}


class MaisonAlhambraTwelveNewIdentitiesTests(unittest.TestCase):
    def test_new_identities_have_official_sources_and_unique_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "maison_alhambra_catalog")
        for name, (product_id, url, size, variant_id) in EXPECTED.items():
            with self.subTest(product=name):
                products = [p for p in CATALOG["products"] if p.get("brand_name") == "Maison Alhambra" and p.get("canonical_name") == name]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("product_id"), product_id)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), variant_id)
                self.assertEqual(variants[0].get("size_ml"), size)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)
                registry_rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(registry_rows), 1)
                self.assertEqual(registry_rows[0].get("formats_ml"), [size])


if __name__ == "__main__":
    unittest.main()
