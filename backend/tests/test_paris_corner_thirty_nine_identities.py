"""Regression coverage for the consolidated Paris Corner official-page batch."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "A Chaos In The Ocean": ("SH-PARIS-CORNER-A-CHAOS-IN-THE-OCEAN", "https://ae.pariscorner.com/products/a-chaos-in-the-ocean-valar-series-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-A-CHAOS-IN-THE-OCEAN-100-000"),
    "A Walk on Dirt": ("SH-PARIS-CORNER-A-WALK-ON-DIRT", "https://ae.pariscorner.com/products/a-walk-on-dirt-valar-series-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-A-WALK-ON-DIRT-100-000"),
    "Amber Oud": ("SH-PARIS-CORNER-AMBER-OUD", "https://ae.pariscorner.com/products/amber-oud-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-AMBER-OUD-100-000"),
    "Arabian Oryx Intense Oud": ("SH-PARIS-CORNER-ARABIAN-ORYX-INTENSE-OUD", "https://ae.pariscorner.com/products/intense-oud-arabian-oryx-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-ARABIAN-ORYX-INTENSE-OUD-100-000"),
    "Arabian Oryx Intense Oud Saffron": ("SH-PARIS-CORNER-ARABIAN-ORYX-INTENSE-OUD-SAFFRON", "https://ae.pariscorner.com/products/intense-oud-saffron-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-ARABIAN-ORYX-INTENSE-OUD-SAFFRON-100-000"),
    "Aseerah": ("SH-PARIS-CORNER-ASEERAH", "https://ae.pariscorner.com/products/aseerah-eau-de-parfum-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-ASEERAH-100-000"),
    "Autobiography Citron Vanille": ("SH-PARIS-CORNER-AUTOBIOGRAPHY-CITRON-VANILLE", "https://ae.pariscorner.com/products/citron-vanille-65-ml", 65, "Eau de Parfum", "SHV-SH-PARIS-CORNER-AUTOBIOGRAPHY-CITRON-VANILLE-65-000"),
    "Autobiography Oh Boy": ("SH-PARIS-CORNER-AUTOBIOGRAPHY-OH-BOY", "https://ae.pariscorner.com/products/oh-boy-65ml", 65, "Eau de Parfum", "SHV-SH-PARIS-CORNER-AUTOBIOGRAPHY-OH-BOY-65-000"),
    "Autobiography Salty Breeze": ("SH-PARIS-CORNER-AUTOBIOGRAPHY-SALTY-BREEZE", "https://ae.pariscorner.com/products/salty-breeze-autobiography-65ml", 65, "Eau de Parfum", "SHV-SH-PARIS-CORNER-AUTOBIOGRAPHY-SALTY-BREEZE-65-000"),
    "Autobiography Supreme Gold": ("SH-PARIS-CORNER-AUTOBIOGRAPHY-SUPREME-GOLD", "https://ae.pariscorner.com/products/supreme-gold-65-ml", 65, "Eau de Parfum", "SHV-SH-PARIS-CORNER-AUTOBIOGRAPHY-SUPREME-GOLD-65-000"),
    "Cedrat Essence": ("SH-PARIS-CORNER-CEDRAT-ESSENCE", "https://ae.pariscorner.com/products/cedrat-essence-75ml", 75, "Eau de Parfum", "SHV-SH-PARIS-CORNER-CEDRAT-ESSENCE-75-000"),
    "Celestial": ("SH-PARIS-CORNER-CELESTIAL", "https://ae.pariscorner.com/products/celestial-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-CELESTIAL-100-000"),
    "Cloud Born": ("SH-PARIS-CORNER-CLOUD-BORN", "https://ae.pariscorner.com/products/cloud-born-eau-de-parfum-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-CLOUD-BORN-100-000"),
    "Corazon Bourbon": ("SH-PARIS-CORNER-CORAZON-BOURBON", "https://ae.pariscorner.com/products/corazon-bourbon-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-CORAZON-BOURBON-100-000"),
    "Corazon Le Parfum": ("SH-PARIS-CORNER-CORAZON-LE-PARFUM", "https://ae.pariscorner.com/products/corazon-le-parfum-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-CORAZON-LE-PARFUM-100-000"),
    "Factory Edition Camp Fire": ("SH-PARIS-CORNER-FACTORY-EDITION-CAMP-FIRE", "https://ae.pariscorner.com/products/factory-edition-camp-fire-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-FACTORY-EDITION-CAMP-FIRE-100-000"),
    "Factory Edition Just Bergamot": ("SH-PARIS-CORNER-FACTORY-EDITION-JUST-BERGAMOT", "https://ae.pariscorner.com/products/factory-edition-just-bergamot-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-FACTORY-EDITION-JUST-BERGAMOT-100-000"),
    "Factory Edition Rich Santal": ("SH-PARIS-CORNER-FACTORY-EDITION-RICH-SANTAL", "https://ae.pariscorner.com/products/factory-edition-rich-santal-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-FACTORY-EDITION-RICH-SANTAL-100-000"),
    "Factory Edition Ultra Citrus": ("SH-PARIS-CORNER-FACTORY-EDITION-ULTRA-CITRUS", "https://ae.pariscorner.com/products/factory-edition-ultra-citrus-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-FACTORY-EDITION-ULTRA-CITRUS-100-000"),
    "Factory Edition Warm Leather": ("SH-PARIS-CORNER-FACTORY-EDITION-WARM-LEATHER", "https://ae.pariscorner.com/products/factory-edition-warm-leather-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-FACTORY-EDITION-WARM-LEATHER-100-000"),
    "Fascination": ("SH-PARIS-CORNER-FASCINATION", "https://ae.pariscorner.com/products/fascination-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-FASCINATION-100-000"),
    "Fire Your Desire": ("SH-PARIS-CORNER-FIRE-YOUR-DESIRE", "https://ae.pariscorner.com/products/fire-your-desire-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-FIRE-YOUR-DESIRE-100-000"),
    "Forbidden Sugar": ("SH-PARIS-CORNER-FORBIDDEN-SUGAR", "https://ae.pariscorner.com/products/forbidden-sugar-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-FORBIDDEN-SUGAR-100-000"),
    "Hurriya Gingerique": ("SH-PARIS-CORNER-HURRIYA-GINGERIQUE", "https://ae.pariscorner.com/products/hurriya-gingerique-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-HURRIYA-GINGERIQUE-100-000"),
    "Magic Oud in Dark Roses": ("SH-PARIS-CORNER-MAGIC-OUD-IN-DARK-ROSES", "https://ae.pariscorner.com/products/magic-oud-in-dark-roses-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-MAGIC-OUD-IN-DARK-ROSES-100-000"),
    "Magic Oud in Kalimath": ("SH-PARIS-CORNER-MAGIC-OUD-IN-KALIMATH", "https://ae.pariscorner.com/products/magic-oud-in-kalimath-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-MAGIC-OUD-IN-KALIMATH-100-000"),
    "Magic Oud in Sandal Wood": ("SH-PARIS-CORNER-MAGIC-OUD-IN-SANDAL-WOOD", "https://ae.pariscorner.com/products/magic-oud-in-sandal-wood-100ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-MAGIC-OUD-IN-SANDAL-WOOD-100-000"),
    "Ministry of Oud - Amber Oud": ("SH-PARIS-CORNER-1ff62b0b", "https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud", 100, None, "SHV-SH-PARIS-CORNER-1ff62b0b-100-000"),
    "Ministry of Oud - Gladiators Oath": ("SH-PARIS-CORNER-d396a92a", "https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath", 100, None, "SHV-SH-PARIS-CORNER-d396a92a-100-000"),
    "Ministry of Oud - Maestro's Symphony": ("SH-PARIS-CORNER-6936e23b", "https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony", 100, None, "SHV-SH-PARIS-CORNER-6936e23b-100-000"),
    "Ministry of Oud - Nile Whispers": ("SH-PARIS-CORNER-ff928faa", "https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers", 100, None, "SHV-SH-PARIS-CORNER-ff928faa-100-000"),
    "Ministry of Oud - Oud Beyond the Wall": ("SH-PARIS-CORNER-159b9d38", "https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall", 100, None, "SHV-SH-PARIS-CORNER-159b9d38-100-000"),
    "Ministry of Oud - Oud Indonesian": ("SH-PARIS-CORNER-ae6eed96", "https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian", 100, None, "SHV-SH-PARIS-CORNER-ae6eed96-100-000"),
    "Ministry of Oud - Oud Royal": ("SH-PARIS-CORNER-fb16a27a", "https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal", 100, None, "SHV-SH-PARIS-CORNER-fb16a27a-100-000"),
    "Ministry of Oud - Oud Satin": ("SH-PARIS-CORNER-30133d89", "https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin", 100, None, "SHV-SH-PARIS-CORNER-30133d89-100-000"),
    "Ministry of Oud - Romance Reverie": ("SH-PARIS-CORNER-7c4f3c29", "https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie", 100, None, "SHV-SH-PARIS-CORNER-7c4f3c29-100-000"),
    "Ministry of Oud - Strictly Oud": ("SH-PARIS-CORNER-efc71aee", "https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud", 100, None, "SHV-SH-PARIS-CORNER-efc71aee-100-000"),
    "Ministry of Oud Greatest": ("SH-PARIS-CORNER-8a3adfeb", "https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest", 100, None, "SHV-SH-PARIS-CORNER-8a3adfeb-100-000"),
    "Tiramisu Speculoos": ("SH-PARIS-CORNER-39610187", "https://www.pariscornerperfumes.com/products/tiramisu-speculoos-100ml", 100, None, "SHV-SH-PARIS-CORNER-39610187-100-000"),
    "Date Caramel": ("SH-PARIS-CORNER-807b8de9", "https://de.pariscornereurope.com/en/products/date-caramel", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-807b8de9-100-EDP"),
    "Indomitable": ("SH-PARIS-CORNER-INDOMITABLE", "https://de.pariscornereurope.com/en/products/indomitable", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-INDOMITABLE-100-EDP"),
    "Mawj Moscow Mule": ("SH-PARIS-CORNER-MAWJ-MOSCOW-MULE", "https://de.pariscornereurope.com/en/products/paris-corner-mawj-moscow-mule-edp-u-100-ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-MAWJ-MOSCOW-MULE-100-EDP"),
    "Perseviron Fig Hug": ("SH-PARIS-CORNER-18f3d5a4", "https://de.pariscornereurope.com/en/products/pc-fig-hug-perseviron-edp-u-100-ml", 100, "Eau de Parfum", "SHV-SH-PARIS-CORNER-18f3d5a4-100-EDP"),
    "Dusky Vanilla": ("SH-PARIS-CORNER-DUSKY-VANILLA", "https://www.pariscornerperfumes.com/products/dusky-vanilla", 100, None, "SHV-SH-PARIS-CORNER-DUSKY-VANILLA-100-000"),
    "Fig Fete": ("SH-PARIS-CORNER-FIG-FETE", "https://www.pariscornerperfumes.com/products/fig-fete", 100, None, "SHV-SH-PARIS-CORNER-FIG-FETE-100-000"),
    "Khair Peach Delulu": ("SH-PARIS-CORNER-KHAIR-PEACH-DELULU", "https://www.pariscornerperfumes.com/products/khair-peach-delulu", 100, None, "SHV-SH-PARIS-CORNER-KHAIR-PEACH-DELULU-100-000"),
    "Farah": ("SH-PARIS-CORNER-FARAH", "https://www.pariscornerperfumes.com/products/farah", 100, None, "SHV-SH-PARIS-CORNER-FARAH-100-000"),
    "Molten Caramel": ("SH-PARIS-CORNER-MOLTEN-CARAMEL", "https://www.pariscornerperfumes.com/products/molten-caramel", 100, None, "SHV-SH-PARIS-CORNER-MOLTEN-CARAMEL-100-UNSPECIFIED"),
    "Marshmallow Blush": ("SH-PARIS-CORNER-MARSHMALLOW-BLUSH", "https://www.pariscornerperfumes.com/products/marshmallow-blush", 100, None, "SHV-SH-PARIS-CORNER-MARSHMALLOW-BLUSH-100-000"),
}


class ParisCornerThirtyNineIdentitiesTests(unittest.TestCase):
    def test_all_official_detail_rows_and_variants_are_present(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "paris_corner_catalog")
        for name, (product_id, url, size, concentration, variant_id) in EXPECTED.items():
            with self.subTest(product=name):
                products = [p for p in CATALOG["products"] if p.get("brand_name") == "Paris Corner" and p.get("canonical_name") == name]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("product_id"), product_id)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertIn(size, product.get("formats_ml", []))
                if concentration is None:
                    self.assertIsNone(product.get("concentration"))
                else:
                    self.assertEqual(product.get("concentration"), concentration)
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id and v.get("size_ml") == size]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant.get("variant_id"), variant_id)
                self.assertEqual(variant.get("source_url"), url)
                self.assertEqual(variant.get("source_evidence_url"), url)
                if concentration is None:
                    self.assertIsNone(variant.get("concentration"))
                else:
                    self.assertEqual(variant.get("concentration"), concentration)
                family_rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(family_rows), 1)
                self.assertIn(size, family_rows[0].get("formats_ml", []))

    def test_paris_corner_product_and_variant_ids_remain_unique(self):
        products = [p for p in CATALOG["products"] if p.get("brand_name") == "Paris Corner"]
        product_ids = [p["product_id"] for p in products]
        names = [p["canonical_name"].casefold() for p in products]
        variants = [v for v in CATALOG["variants"] if v.get("product_id") in set(product_ids)]
        variant_ids = [v["variant_id"] for v in variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
