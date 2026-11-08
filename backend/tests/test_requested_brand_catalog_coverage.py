"""Regression guard for the user-requested fragrance brand coverage."""
import json
import re
import unicodedata
import unittest
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

# Lower bounds from the reconciled 2026-11-08 catalog snapshot. These are
# canonical fragrance identities, not SKU/variant counts or claims of
# worldwide historical completeness.
MINIMUM_BRAND_COUNTS = {
    "Velixir": 28,
    "Mykonos": 99,
    "Maison Asrar": 120,
    "Khadlaj": 117,
    "Bujairami": 142,
    "Paris Corner": 245,
    "Assaf": 140,
    "Al Wataniah": 86,
    "Armaf": 190,
    "French Avenue": 119,
    "Arabiyat Prestige": 118,
    "Gulf Orchid": 23,
    "Swiss Arabian": 32,
    "Games of Spades": 29,
    "Lattafa": 114,
    "Afnan": 87,
    "Aromatix": 12,
    "Maison Alhambra": 203,
    "Zimaya": 72,
    "Al Haramain": 101,
}


class RequestedBrandCatalogCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = Counter(
            str(row.get("brand_name") or row.get("brand") or "").strip()
            for row in CATALOG.get("products", [])
        )

    def test_every_requested_brand_is_represented(self):
        missing = [
            brand for brand, minimum in MINIMUM_BRAND_COUNTS.items()
            if self.counts.get(brand, 0) < minimum
        ]
        self.assertEqual(
            missing,
            [],
            "Requested brand coverage regressed below the reconciled catalog baseline.",
        )

    def test_requested_brand_rows_have_source_provenance(self):
        requested = set(MINIMUM_BRAND_COUNTS)
        allowed_statuses = {"source_verified_name", "source_listed_name"}
        missing = []
        invalid_status = []
        for index, row in enumerate(CATALOG.get("products", [])):
            brand = str(row.get("brand_name") or row.get("brand") or "").strip()
            if brand not in requested:
                continue
            if not str(row.get("source_url") or "").strip():
                missing.append(f"products[{index}] {brand}: missing source_url")
            if row.get("identity_status") not in allowed_statuses:
                invalid_status.append(
                    f"products[{index}] {brand}: invalid identity_status "
                    f"{row.get('identity_status')!r}"
                )
        self.assertEqual(missing, [])
        self.assertEqual(invalid_status, [])

    def test_aromatix_line_is_present(self):
        self.assertGreaterEqual(self.counts.get("Aromatix", 0), 1)

    def test_maison_asrar_royal_collection_is_complete_against_official_listing(self):
        names = {
            str(row.get("canonical_name") or row.get("name") or "").strip().casefold()
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "Maison Asrar"
        }
        # Nine individual fragrances shown in Maison Asrar's official UAE
        # Royal Collection. "The Royal" on the UK storefront is a bundle of
        # Legacy, Majesty and Vanguard, not a separate fragrance identity.
        expected = (
            "Belgravia", "Legacy", "Vanguard", "Regent", "Majesty",
            "Heritage", "Monarch", "Treasure", "Imperial",
        )
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(name.casefold(), names)

    def test_french_avenue_new_arrivals_are_present_as_verified_100ml_variants(self):
        products = {
            str(row.get("canonical_name") or row.get("name") or "").strip(): row
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "French Avenue"
        }
        variants = CATALOG.get("variants", [])
        expected = {
            "Eclipse": ("https://frenchavenue.com/products/eclipse", "Extrait de Parfum"),
            "Eclipse Nova": (
                "https://frenchavenue.com/products/eclipse-nova-extrait",
                "Extrait de Parfum",
            ),
        }
        for name, (source_url, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                self.assertEqual(products[name].get("identity_status"), "source_verified_name")
                self.assertEqual(products[name].get("source_url"), source_url)
                self.assertEqual(products[name].get("concentration"), concentration)
                matching_variants = [
                    row for row in variants if row.get("product_id") == products[name]["product_id"]
                ]
                self.assertTrue(
                    any(
                        row.get("size_ml") == 100
                        and row.get("concentration") == concentration
                        for row in matching_variants
                    )
                )

    def test_paris_corner_midnight_sin_official_page_and_100ml_variant_are_verified(self):
        row = next(
            (
                product
                for product in CATALOG.get("products", [])
                if str(product.get("brand_name") or product.get("brand") or "").strip() == "Paris Corner"
                and str(product.get("canonical_name") or product.get("name") or "").strip() == "Midnight Sin by Daniel René"
            ),
            None,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(
            row.get("source_url"),
            "https://www.pariscornerperfumes.com/products/midnight-sin-by-daniel-rene",
        )
        self.assertTrue(
            any(
                variant.get("product_id") == row["product_id"]
                and variant.get("size_ml") == 100
                for variant in CATALOG.get("variants", [])
            )
        )

    def test_maison_alhambra_official_new_products_and_leonie_pages_are_verified(self):
        expected = {
            "Minerale Gold": "https://maisonalhambra-usa.com/products/maison-alhambra-minerale-gold-eau-de-parfum-for-everyone",
            "Victorioso Fearless": "https://maisonalhambra-usa.com/products/maison-alhambra-victorioso-fearless-eau-de-parfum-for-everyone",
            "The Memory of Oud": "https://maisonalhambra-usa.com/products/maison-alhambra-the-memory-of-oud-eau-de-parfum-for-everyone",
            "Sceptre Oceana": "https://maisonalhambra-usa.com/products/maison-alhambra-sceptre-oceana-eau-de-parfum-for-everyone",
            "Leonie": "https://maisonalhambra-usa.com/collections/womens-best-seller/products/maison-alhambra-leonie-eau-de-parfum-for-women",
            "Leonie Intense": "https://maisonalhambra-usa.com/products/maison-alhambra-leonie-intense-eau-de-parfum-for-women",
        }
        products = {
            str(row.get("canonical_name") or row.get("name") or "").strip(): row
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "Maison Alhambra"
        }
        for name, source_url in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("concentration"), "Eau de Parfum")
                self.assertTrue(
                    any(
                        variant.get("product_id") == row["product_id"]
                        and variant.get("size_ml") == 100
                        and variant.get("concentration") == "Eau de Parfum"
                        for variant in CATALOG.get("variants", [])
                    )
                )

    def test_zimaya_verified_new_launches_have_official_pages_and_100ml_edp_variants(self):
        expected = {
            "Kibria Supremo": "https://ro.zimayaperfumes.com/products/kibria-supremo",
            "Oscar Platinum": "https://fr.zimayaperfumes.com/products/oscar-platinum",
            "Zukhruf Peach Please": "https://de.zimayaperfumes.com/en/products/zukhruf-peach",
            "Mazaaj Rhythm": "https://zimayaperfumes.com/products/mazaaj-rhythm",
            "Tiramisu S’mores": "https://zimayaperfumes.com/products/tiramisu-s-mores",
        }
        products = {
            str(row.get("canonical_name") or row.get("name") or "").strip(): row
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "Zimaya"
        }
        for name, source_url in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("concentration"), "Eau de Parfum")
                self.assertTrue(
                    any(
                        variant.get("product_id") == row["product_id"]
                        and variant.get("size_ml") == 100
                        and variant.get("concentration") == "Eau de Parfum"
                        for variant in CATALOG.get("variants", [])
                    )
                )

    def test_afnan_9pm_night_out_official_product_page_and_variant_are_verified(self):
        row = next(
            (
                product
                for product in CATALOG.get("products", [])
                if str(product.get("brand_name") or product.get("brand") or "").strip() == "Afnan"
                and str(product.get("canonical_name") or product.get("name") or "").strip() == "9 PM Night Out"
            ),
            None,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), "https://de.afnan.com/en/products/9pm-night-out")
        self.assertEqual(row.get("concentration"), "Extrait de Parfum")
        self.assertTrue(
            any(
                variant.get("product_id") == row["product_id"]
                and variant.get("size_ml") == 100
                and variant.get("concentration") == "Extrait de Parfum"
                for variant in CATALOG.get("variants", [])
            )
        )

    def test_prune_hypnos_official_product_page_and_variant_are_verified(self):
        row = next(
            (
                product
                for product in CATALOG.get("products", [])
                if str(product.get("brand_name") or product.get("brand") or "").strip() == "French Avenue"
                and str(product.get("canonical_name") or product.get("name") or "").strip() == "Prune Hypnos"
            ),
            None,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), "https://frenchavenue.com/products/prune-hypnos")
        self.assertEqual(row.get("concentration"), "Eau de Parfum")
        self.assertTrue(
            any(
                variant.get("product_id") == row["product_id"]
                and variant.get("size_ml") == 100
                and variant.get("concentration") == "Eau de Parfum"
                for variant in CATALOG.get("variants", [])
            )
        )

    def test_french_avenue_official_product_pages_and_variants_are_verified(self):
        products = {
            str(row.get("canonical_name") or row.get("name") or "").strip(): row
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "French Avenue"
        }
        expected = {
            "Le Falcon": (
                "https://frenchavenue.com/products/le-falcon",
                "Eau de Parfum",
            ),
            "Le Falcon Dubai": (
                "https://frenchavenue.com/products/le-falcon-dubai",
                "Eau de Parfum",
            ),
            "Spirito Ignite": (
                "https://frenchavenue.com/products/spirito-ignite",
                "Extrait de Parfum",
            ),
        }
        for name, (source_url, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("concentration"), concentration)
                self.assertTrue(
                    any(
                        variant.get("product_id") == row["product_id"]
                        and variant.get("size_ml") == 100
                        and variant.get("concentration") == concentration
                        for variant in CATALOG.get("variants", [])
                    )
                )


    def test_paris_corner_eight_official_detail_pages_and_100ml_variants_are_verified(self):
        expected = {
            "Dulzura Vanilla Envie": ("https://www.pariscornerperfumes.com/products/dulzura-vanilla-envie", None),
            "Empire de la Rouge": ("https://www.pariscornerperfumes.com/products/empire-de-la-rouge", "Eau de Parfum"),
            "Green Bet": ("https://www.pariscornerperfumes.com/products/green-bet", None),
            "Heer": ("https://www.pariscornerperfumes.com/products/heer", None),
            "Marshmallow Blush": ("https://www.pariscornerperfumes.com/products/marshmallow-blush", None),
            "Oravea": ("https://www.pariscornerperfumes.com/products/oravea", "Eau de Parfum"),
            "Rawq": ("https://www.pariscornerperfumes.com/products/rawq", None),
            "The Show Magnifique": ("https://www.pariscornerperfumes.com/products/the-show-magnifique", None),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertIn(100, row.get("formats_ml", []))
                matching = [
                    v for v in variants
                    if v.get("product_id") == row["product_id"] and v.get("size_ml") == 100
                ]
                self.assertEqual(len(matching), 1)
                if concentration is None:
                    self.assertNotIn("concentration", row)
                    self.assertNotIn("concentration", matching[0])
                else:
                    self.assertEqual(row.get("concentration"), concentration)
                    self.assertEqual(matching[0].get("concentration"), concentration)


    def test_paris_corner_eleven_more_official_pages_and_variants_are_verified(self):
        expected = {
            "Tawaaq": ("https://www.pariscornerperfumes.com/products/tawaaq", 100, None),
            "Lueur d'Espoir Noche": ("https://www.pariscornerperfumes.com/products/lueur-noche", 100, None),
            "Lueur d'Espoir Arena": ("https://www.pariscornerperfumes.com/products/lueur-arena", 100, "Eau de Parfum"),
            "Lueur d'Espoir Ambre": ("https://www.pariscornerperfumes.com/products/lueur-ambre", 100, None),
            "North Stag Neuf IX": ("https://www.pariscornerperfumes.com/products/north-stag-neuf-ix", 100, "Extrait de Parfum"),
            "North Stag Sept VII": ("https://www.pariscornerperfumes.com/products/north-stag-sept-vii", 100, "Extrait de Parfum"),
            "Rose de Nuit": ("https://www.pariscornerperfumes.com/products/rose-de-nuit", 100, "Eau de Parfum"),
            "Super Crush Emir": ("https://www.pariscornerperfumes.com/products/super-crush-emir", 75, None),
            "Ministry of Oud - Thailand Oud in Cairo": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-thailand-oud-in-cairo", 100, None),
            "Charuto Mysterious Tobacco": ("https://www.pariscornerperfumes.com/products/paris-corner-perfumes", 100, "Eau de Parfum"),
            "North Stag Huit VIII": ("https://www.pariscornerperfumes.com/products/north-stag-huit-viii", 100, "Extrait de Parfum"),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, size_ml, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertIn(size_ml, row.get("formats_ml", []))
                matching = [
                    v for v in variants
                    if v.get("product_id") == row["product_id"] and v.get("size_ml") == size_ml
                ]
                self.assertEqual(len(matching), 1)
                if concentration is None:
                    self.assertNotIn("concentration", row)
                    self.assertNotIn("concentration", matching[0])
                else:
                    self.assertEqual(row.get("concentration"), concentration)
                    self.assertEqual(matching[0].get("concentration"), concentration)


    def test_north_stag_collection_individual_pages_and_variants_are_verified(self):
        expected = {
            "Quatre IV Expressions North Stag": ("https://www.pariscornerperfumes.com/products/quatre-iv-expressions-north-stag", None),
            "Trois III Expressions North Stag": ("https://www.pariscornerperfumes.com/products/trois-iii-expressions-north-stag", None),
            "Deux II Expressions North Stag": ("https://www.pariscornerperfumes.com/products/deux-ii-expressions-north-stag-100ml", 100),
            "Un I Expressions North Stag": ("https://www.pariscornerperfumes.com/products/un-i-expressions-north-stag", None),
            "North Stag Phenomenal Quatorze XIV": ("https://www.pariscornerperfumes.com/products/north-stag-phenomenal-quatorze-xiv", 100),
            "North Stag Hypnotic Oud Quinze XV": ("https://www.pariscornerperfumes.com/products/north-stag-hypnotic-oud-quinze-xv", 100),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, size_ml) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                if size_ml is None:
                    self.assertNotIn("formats_ml", row)
                    self.assertFalse(any(v.get("product_id") == row["product_id"] for v in variants))
                else:
                    self.assertIn(size_ml, row.get("formats_ml", []))
                    matching = [
                        v for v in variants
                        if v.get("product_id") == row["product_id"] and v.get("size_ml") == size_ml
                    ]
                    self.assertEqual(len(matching), 1)
                self.assertNotIn("concentration", row)


    def test_paris_corner_atoof_official_page_and_100ml_variant_are_verified(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        self.assertIn("Atoof", products)
        row = products["Atoof"]
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), "https://www.pariscornerperfumes.com/products/atoof")
        self.assertIn(100, row.get("formats_ml", []))
        matching = [
            v for v in CATALOG.get("variants", [])
            if v.get("product_id") == row["product_id"] and v.get("size_ml") == 100
        ]
        self.assertEqual(len(matching), 1)
        self.assertNotIn("concentration", row)
        self.assertNotIn("concentration", matching[0])

    def test_aromatix_signature_collection_is_present(self):
        names = {
            str(row.get("canonical_name") or row.get("name") or "").strip().casefold()
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "Aromatix"
        }
        expected = (
            "Teas Me", "Frostbite", "Naughty Dates", "Sun Kissed",
            "Forbidden Fruit", "Magnetiq", "Platine Blanc", "X Xandal",
            "Royal Taboo", "Carnal Desire",
        )
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(name.casefold(), names)



    def test_paris_corner_four_more_official_pages_and_100ml_variants_are_verified(self):
        expected = {
            "Aira": "https://www.pariscornerperfumes.com/products/aira",
            "Ciao Citrus": "https://www.pariscornerperfumes.com/products/ciao-citrus",
            "Fatal Embrace": "https://www.pariscornerperfumes.com/products/fatal-embrace",
            "Wayfarer Infusion": "https://www.pariscornerperfumes.com/products/wayfarer-infusion",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, source_url in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertIn(100, row.get("formats_ml", []))
                matching = [
                    v for v in variants
                    if v.get("product_id") == row["product_id"] and v.get("size_ml") == 100
                ]
                self.assertEqual(len(matching), 1)
                self.assertNotIn("concentration", row)
                self.assertNotIn("concentration", matching[0])


    def test_mykonos_fragrantica_omissions_have_detail_pages_and_explicit_variants(self):
        expected = {
            "Berry Caramel Pancake": (
                "https://officialmykonos.de/products/mykonos-berry-caramel-pancake",
                50,
                "Eau de Parfum",
            ),
            "Avra Kehdabra": (
                "https://officialmykonos.de/products/mykonos-x-paola-serena-avra-kehdabra",
                100,
                "Eau de Parfum",
            ),
            "Dolce Cherry": (
                "https://officialmykonos.de/products/mykonos-x-sapeyeeee-dolce-cherry",
                50,
                "Extrait de Parfum",
            ),
            "Violette": (
                "https://officialmykonos.de/products/mykonos-x-violenzia-violette",
                100,
                "Eau de Parfum",
            ),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, size_ml, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("concentration"), concentration)
                self.assertIn(size_ml, row.get("formats_ml", []))
                matching = [
                    variant for variant in variants
                    if variant.get("product_id") == row["product_id"]
                    and variant.get("size_ml") == size_ml
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("concentration"), concentration)


    def test_mykonos_current_eu_catalog_additions_and_confirmed_variants(self):
        expected = {
            "Daydream": ("https://mykonosperfumes.eu/products/mykonos-daydream", 100, "Extrait de Parfum"),
            "Inception Reimagined": ("https://mykonosperfumes.eu/products/mykonos-inception-reimagined", 100, "Extrait de Parfum"),
            "Monaco Royale Black": ("https://mykonosperfumes.eu/products/mykonos-monaco-royale-black", 50, "Extrait de Parfum"),
            "Shape Shift": ("https://mykonosperfumes.eu/products/mykonos-shape-shift", 100, "Extrait de Parfum"),
            "Forever Musc": ("https://mykonosperfumes.eu/products/mykonos-forever-musc", 100, "Eau de Parfum"),
            "Soft Hour x NCT Haechan": ("https://mykonosperfumes.eu/products/mykonos-x-nct-haechan-soft-hour", 100, "Extrait de Parfum"),
        }
        products = {row.get("canonical_name"): row for row in CATALOG.get("products", []) if row.get("brand_name") == "Mykonos"}
        variants = CATALOG.get("variants", [])
        for name, (url, size, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("source_url"), url)
                self.assertIn(size, row.get("formats_ml", []))
                matched = [v for v in variants if v.get("product_id") == row["product_id"] and v.get("size_ml") == size and v.get("concentration") == concentration]
                self.assertEqual(len(matched), 1)
        black = products["Monaco Royale Black"]
        self.assertEqual(sorted(v.get("size_ml") for v in variants if v.get("product_id") == black["product_id"]), [50, 100])


    def test_mykonos_imperium_is_distinct_from_empire_x_rrq(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        self.assertIn("Imperium", products)
        self.assertIn("Empire x RRQ", products)
        self.assertNotIn("Imperium", products["Empire x RRQ"].get("aliases", []))
        self.assertNotIn("Mykonos Imperium", products["Empire x RRQ"].get("aliases", []))
        imperium = products["Imperium"]
        self.assertEqual(
            imperium.get("source_url"),
            "https://officialmykonos.com/products/mykonos-imperium-extrait-de-parfum-100ml",
        )
        self.assertEqual(imperium.get("formats_ml"), [100])
        self.assertEqual(imperium.get("concentration"), "Extrait de Parfum")
        variants = [
            row for row in CATALOG.get("variants", [])
            if row.get("product_id") == imperium["product_id"] and row.get("size_ml") == 100
        ]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].get("concentration"), "Extrait de Parfum")

    def test_mykonos_inspire_parfum_fragrantica_name_is_an_alias(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        self.assertIn("Inspire Parfum", products["Inspire Perfume"].get("aliases", []))

    def test_mykonos_announced_names_are_catalogued_without_guessing_variants(self):
        expected = {
            "Kingsman": "https://mykonosperfumes.eu/products/mykonos-kingsman",
            "Wallflower": "https://mykonosperfumes.eu/products/mykonos-wallflower",
            "Elysian": "https://mykonosperfumes.eu/products/mykonos-elysian",
            "Undercover": "https://mykonosperfumes.eu/products/mykonos-undercover",
            "Celestial": "https://mykonosperfumes.eu/products/mykonos-celestial",
            "Café Lyon": "https://mykonosperfumes.eu/products/mykonos-cafe-lyon",
            "President": "https://mykonosperfumes.eu/products/mykonos-president",
            "Déjà Vu": "https://mykonosperfumes.eu/products/mykonos-deja-vu",
            "Inspire Perfume": "https://mykonosperfumes.eu/products/mykonos-inspire",
        }
        products = {row.get("canonical_name"): row for row in CATALOG.get("products", []) if row.get("brand_name") == "Mykonos"}
        variants = CATALOG.get("variants", [])
        for name, url in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("source_url"), url)
                self.assertFalse(any(v.get("product_id") == row["product_id"] for v in variants), "Do not invent an unconfirmed size/concentration variant")


    def test_mykonos_fragrantica_legacy_names_are_tracked_without_invented_variants(self):
        expected = ["Adelina", "Bloody Mary", "Crystals", "Eclipse", "Nashi Pear Garden", "Roulette", "Zeus", "It's Not Ella"]
        products = {row.get("canonical_name"): row for row in CATALOG.get("products", []) if row.get("brand_name") == "Mykonos"}
        variants = CATALOG.get("variants", [])
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(name, products)
                self.assertEqual(products[name].get("identity_status"), "source_listed_name")
                self.assertEqual(products[name].get("source_url"), "https://www.fragrantica.com/designers/Mykonos.html")
                self.assertFalse(any(v.get("product_id") == products[name]["product_id"] for v in variants))


    def test_mykonos_fragrantica_spelling_aliases_resolve_to_existing_identities(self):
        expected_aliases = {
            "Jynx": ["Jinx"],
            "Nautilus": ["Nautilius"],
            "Empire x RRQ": ["Empire", "Mykonos Empire"],
            "California": ["California Signature"],
            "Xoxo Rosy": ["XoXo, Rosy"],
            "Shades Perfume": ["Shades Parfum"],
            "Affair": ["Intimate Affair"],
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        for canonical_name, aliases in expected_aliases.items():
            with self.subTest(canonical_name=canonical_name):
                self.assertIn(canonical_name, products)
                for alias in aliases:
                    self.assertIn(alias, products[canonical_name].get("aliases", []))

    def test_mykonos_fragrantica_only_legacy_names_are_not_given_guessed_variants(self):
        names = {
            "Adelina", "Bloody Mary", "Crystals", "Eclipse",
            "Nashi Pear Garden", "Roulette", "Zeus", "It's Not Ella",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        variants = CATALOG.get("variants", [])
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("source_url"), "https://www.fragrantica.com/designers/Mykonos.html")
                self.assertEqual(row.get("identity_status"), "source_listed_name")
                self.assertFalse(
                    any(v.get("product_id") == row["product_id"] for v in variants),
                    "Do not infer size or concentration from a designer index entry",
                )

    def test_mykonos_fragrantica_body_mists_are_not_misclassified_as_perfumes(self):
        excluded = {"Love, Rosy", "Lychee Breeze", "Matcha Sundays"}
        names = {
            row.get("canonical_name")
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        self.assertTrue(excluded.isdisjoint(names))

    def test_mykonos_complete_eu_perfume_index_is_present_and_body_mists_are_excluded(self):
        # 89 perfume identities in the authorized EU retailer's current A-Z index.
        # The 12 separately named Fragrance Mist products are intentionally
        # excluded from the perfume catalog. Soft Hour x NCT Haechan is tracked
        # separately as an announced new-release listing.
        expected_perfumes = {
            "Affair", "Aphrodite", "Baby Love", "Berry Caramel Pancake",
            "Black Opera", "Blaze", "Blossom", "Bonfire Vanilla", "Cafe Drops",
            "Café Lyon", "California Blue", "California Club", "California",
            "Caramel Fudge Cookie", "Celestial", "Coconut Dreams", "Conquer",
            "Constantine", "Crimson", "Dark Secret", "Daydream", "Down to Earth",
            "Dreamscape", "Déjà Vu", "Elysian", "Empire x RRQ", "Enchanted",
            "Forever Musc", "Hawaiian Crush", "Inception", "Inception Reimagined",
            "Inferno", "Inspire Perfume", "Ivory", "Kingsman", "Luminos",
            "Marbella", "Matcha Latte", "Mayfair", "Memoir of Meri", "Milk Drops",
            "Monaco Royale Black", "Monaco Royale", "Moroccan Vanilla", "Musk Aura",
            "Nautilus", "On The Rocks", "Only You", "Pandan Sticky Rice",
            "Paradise", "Penthouse", "Pink Beach", "Pink Drops",
            "Pistachio Cream Cake", "President", "Reflection Elixir", "Reflection",
            "Royal Ispahan", "Sansa", "Satin Blanc", "Senja", "Seven Roses",
            "Shades Perfume", "Shape Shift", "Silent Whisper", "Slow Living",
            "Sorrento", "Sparkling Rosé", "Stilettos",
            "Tea Poetry", "Undercover", "Untamed", "Utopia", "Vanilla Clouds",
            "Verve", "Wallflower", "When in Paris", "MyEgo", "Once Upon Don",
            "Avra Kehdabra", "Jynx", "Chai Crema Latte", "Dolce Cherry", "Rouge",
            "Glitch", "Invade", "Violette", "Xoxo Rosy", "Zora",
        }
        body_mists = {
            "Bacca Rouge", "Beauty", "Blue Love", "Blue Peony", "British Pear",
            "Juicy Me", "Magnifique", "Malika", "Purple Beauty",
            "Purple Beauty Halal", "Star Kiss", "Sweet Pea",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        self.assertEqual(len(expected_perfumes), 89)
        self.assertTrue(expected_perfumes.issubset(products.keys()))
        self.assertTrue(body_mists.isdisjoint(products.keys()))
        self.assertIn("Soft Hour x NCT Haechan", products)
        soft_hour = products["Soft Hour x NCT Haechan"]
        self.assertEqual(soft_hour.get("formats_ml"), [100])
        self.assertEqual(soft_hour.get("concentration"), "Extrait de Parfum")


    def test_mykonos_empire_x_rrq_keeps_its_own_identity_and_variants(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        empire = products["Empire x RRQ"]
        self.assertEqual(
            empire.get("source_url"),
            "https://mykonosperfumes.eu/products/mykonos-x-rrq-empire",
        )
        self.assertEqual(empire.get("formats_ml"), [50, 100])
        self.assertEqual(empire.get("concentration"), "Extrait de Parfum")
        self.assertNotIn("Imperium", empire.get("aliases", []))
        variants = [
            row for row in CATALOG.get("variants", [])
            if row.get("product_id") == empire["product_id"]
        ]
        self.assertEqual(
            {row.get("size_ml") for row in variants},
            {50, 100},
        )

    def test_mykonos_california_signature_is_an_alias_of_california(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        self.assertIn("California", products)
        self.assertNotIn("California Signature", products)
        self.assertIn(
            "California Signature",
            products["California"].get("aliases", []),
        )
        self.assertEqual(
            products["California"].get("source_url"),
            "https://officialmykonos.com/products/mykonos-california-signature-50ml",
        )
        variants = [
            row for row in CATALOG.get("variants", [])
            if row.get("product_id") == products["California"]["product_id"]
        ]
        self.assertEqual({v.get("size_ml") for v in variants}, {50, 100})
        self.assertTrue(all(
            any(alias.startswith("California Signature ") for alias in v.get("aliases", []))
            for v in variants
        ))



    def test_mykonos_fragrantica_fine_fragrance_listing_is_covered(self):
        # Fragrantica's 84 count includes three Body Mists. The 81 fine
        # fragrance names below are matched against canonical names and aliases.
        expected = [
          "Adelina",
          "Affair",
          "Avra Kehdabra",
          "Baby Love",
          "Berry Caramel Pancake",
          "Black Opera",
          "Blaze",
          "Bloody Mary",
          "Blossom",
          "Bonfire Vanilla",
          "Cafe Drops",
          "Chai Crema Latte",
          "Coconut Dreams",
          "Conquer",
          "Constantine",
          "Crimson",
          "Crystals",
          "Dolce Cherry",
          "Down to Earth",
          "Eclipse",
          "Empire",
          "Enchanted",
          "Glitch",
          "Imperium",
          "Inception",
          "Inferno",
          "Invade",
          "Ivory",
          "Jinx",
          "Luminos",
          "Marbella",
          "Matcha Latte",
          "Mayfair",
          "Memoir of Meri",
          "Milk Drops",
          "Monaco Royale",
          "Moroccan Vanilla",
          "Nashi Pear Garden",
          "Nautilius",
          "On The Rocks",
          "Once upon Don",
          "Pandan Sticky Rice",
          "Penthouse",
          "Pink Beach",
          "Pink Drops",
          "Reflection",
          "Reflection Elixir",
          "Rouge",
          "Roulette",
          "Royal Ispahan",
          "Seven Roses",
          "Slow Living",
          "Sorrento",
          "Stilettos",
          "Untamed",
          "Utopia",
          "Verve",
          "Violette",
          "When in Paris",
          "Zeus",
          "Dreamscape",
          "Silent Whisper",
          "Hawaiian Crush",
          "Tea Poetry",
          "California",
          "California Blue",
          "California Club",
          "California Signature",
          "Vanilla Clouds",
          "It's Not Ella",
          "Musk Aura",
          "Paradise",
          "Caramel Fudge Cookie",
          "XoXo, Rosy",
          "Aphrodite",
          "Sansa",
          "Senja",
          "Zora",
          "Dark Secret",
          "Satin Blanc",
          "Sparkling Rosé"
]
        products = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        ]
        def normalize(value):
            import unicodedata
            value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
            return "".join(ch.lower() for ch in value if ch.isalnum())
        known = {
            normalize(name)
            for row in products
            for name in [row.get("canonical_name", "")] + row.get("aliases", [])
        }
        missing = [name for name in expected if normalize(name) not in known]
        self.assertEqual(missing, [])

    def test_mykonos_jinx_and_nautilius_are_aliases_not_duplicate_products(self):
        products = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        ]
        jynx = next(row for row in products if row.get("canonical_name") == "Jynx")
        nautilus = next(row for row in products if row.get("canonical_name") == "Nautilus")
        self.assertIn("Jinx", jynx.get("aliases", []))
        self.assertIn("Nautilius", nautilus.get("aliases", []))


    def test_mykonos_fragrantica_84_listing_has_all_81_fragrance_names(self):
        def normalize(value):
            value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
            return re.sub(r"[^a-z0-9]", "", value.casefold())

        mykonos = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        ]
        searchable = {
            normalize(name)
            for row in mykonos
            for name in [row.get("canonical_name"), *(row.get("aliases") or [])]
            if name
        }
        fragrantica_fragrance_names = (
            "Adelina", "Affair", "Avra Kehdabra", "Baby Love", "Berry Caramel Pancake",
            "Black Opera", "Blaze", "Bloody Mary", "Blossom", "Bonfire Vanilla",
            "Cafe Drops", "Chai Crema Latte", "Coconut Dreams", "Conquer", "Constantine",
            "Crimson", "Crystals", "Dolce Cherry", "Down to Earth", "Eclipse", "Empire",
            "Enchanted", "Glitch", "Imperium", "Inception", "Inferno", "Invade", "Ivory",
            "Jinx", "Luminos", "Marbella", "Matcha Latte", "Mayfair", "Memoir of Meri",
            "Milk Drops", "Monaco Royale", "Moroccan Vanilla", "Nashi Pear Garden",
            "Nautilius", "On The Rocks", "Once upon Don", "Pandan Sticky Rice",
            "Penthouse", "Pink Beach", "Pink Drops", "Reflection", "Reflection Elixir",
            "Rouge", "Roulette", "Royal Ispahan", "Seven Roses", "Slow Living", "Sorrento",
            "Stilettos", "Untamed", "Utopia", "Verve", "Violette", "When in Paris", "Zeus",
            "Dreamscape", "Silent Whisper", "Hawaiian Crush", "Tea Poetry", "California",
            "California Blue", "California Club", "California Signature", "Vanilla Clouds",
            "It's Not Ella", "Musk Aura", "Paradise", "Caramel Fudge Cookie", "XoXo, Rosy",
            "Aphrodite", "Sansa", "Senja", "Zora", "Dark Secret", "Satin Blanc", "Sparkling Rosé",
        )
        missing = [
            name for name in fragrantica_fragrance_names
            if normalize(name) not in searchable
        ]
        self.assertEqual(missing, [])

    def test_mykonos_empire_and_imperium_are_distinct_fragrances(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        self.assertIn("Empire x RRQ", products)
        self.assertIn("Imperium", products)
        self.assertNotIn("Imperium", products["Empire x RRQ"].get("aliases", []))
        imperium = products["Imperium"]
        self.assertEqual(
            imperium.get("source_url"),
            "https://officialmykonos.com/products/mykonos-imperium-extrait-de-parfum-100ml",
        )
        self.assertEqual(imperium.get("formats_ml"), [100])
        self.assertEqual(imperium.get("concentration"), "Extrait de Parfum")
        variants = [
            row for row in CATALOG.get("variants", [])
            if row.get("product_id") == imperium.get("product_id")
        ]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].get("size_ml"), 100)
        self.assertEqual(variants[0].get("concentration"), "Extrait de Parfum")


    def test_mykonos_imperium_is_a_distinct_official_fragrance(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        self.assertIn("Imperium", products)
        self.assertIn("Empire x RRQ", products)
        self.assertNotEqual(
            products["Imperium"].get("product_id"),
            products["Empire x RRQ"].get("product_id"),
        )
        self.assertEqual(
            products["Imperium"].get("source_url"),
            "https://officialmykonos.com/products/mykonos-imperium-extrait-de-parfum-100ml",
        )
        self.assertEqual(products["Imperium"].get("formats_ml"), [100])

    def test_velixir_official_catalog_has_all_28_perfumes_and_four_confirmed_sizes(self):
        expected_concentrations = {
            "Adonis": "Eau de Parfum",
            "Aphrodite": "Eau de Parfum",
            "Apollo": "Eau de Parfum",
            "Ares": "Eau de Parfum",
            "Artemis": "Eau de Parfum",
            "Asteria": "Eau de Parfum",
            "Athena": "Eau de Parfum",
            "Comus": "Extrait de Parfum",
            "Concordia": "Eau de Parfum",
            "Demeter": "Eau de Parfum",
            "Ether": "Extrait de Parfum",
            "Galatea": "Eau de Parfum",
            "Harmonia": "Eau de Parfum",
            "Helios": "Eau de Parfum",
            "Hera": "Eau de Parfum",
            "Himeros": "Eau de Parfum",
            "Icarus": "Eau de Parfum",
            "Morpheus": "Eau de Parfum",
            "Narcisus": "Eau de Parfum",
            "Nyx": "Eau de Parfum",
            "Orion": "Eau de Parfum",
            "Orpheus": "Extrait de Parfum",
            "Paladin": "Eau de Parfum",
            "Panacea": "Extrait de Parfum",
            "Persephone": "Eau de Parfum",
            "Poseidon": "Eau de Parfum",
            "Selene": "Eau de Parfum",
            "Uranus": "Eau de Parfum",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Velixir"
        }
        variants = CATALOG.get("variants", [])
        expected_sizes = {2, 3, 35, 100}
        self.assertEqual(set(products), set(expected_concentrations))
        self.assertEqual(len(products), 28)
        for name, concentration in expected_concentrations.items():
            with self.subTest(name=name):
                product = products[name]
                self.assertEqual(product.get("concentration"), concentration)
                self.assertEqual(set(product.get("formats_ml", [])), expected_sizes)
                matched = [v for v in variants if v.get("product_id") == product["product_id"]]
                self.assertEqual({v.get("size_ml") for v in matched}, expected_sizes)
                self.assertEqual(len(matched), 4)
                self.assertTrue(all(v.get("concentration") == concentration for v in matched))
                self.assertTrue(all(v.get("source_evidence_url") == "https://velixir.co.uk/collections/all" for v in matched))

    def test_velixir_discovery_sets_and_bundles_are_not_canonical_fragrances(self):
        products = {
            row.get("canonical_name")
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Velixir"
        }
        self.assertTrue({"Discovery Set", "The Sacred Four Bundle", "JTC Bundle"}.isdisjoint(products))

    def test_maison_asrar_all_116_reference_fragrances_and_three_retailer_additions_are_present(self):
        expected = [
                  "Belgravia",
                  "Legacy",
                  "Vanguard",
                  "Regent",
                  "Ameer",
                  "Majesty",
                  "Veyra",
                  "Vanilla Aura",
                  "Faris Al Arab",
                  "Vanilla Voyage",
                  "III Thriller",
                  "Last Swim",
                  "Pomme Rouge",
                  "Haven",
                  "Muharib",
                  "Silent Surge",
                  "Treasure",
                  "Hunter",
                  "Imperial",
                  "Monarch",
                  "1963",
                  "Adorable",
                  "Alonoud",
                  "Aseel",
                  "Basma",
                  "Black",
                  "Bloom Bloom",
                  "Bonita",
                  "Casablanca",
                  "Cascade",
                  "Coffee Blend",
                  "Daham",
                  "Date Night",
                  "Dear Jasmine",
                  "Desire",
                  "Dubai London",
                  "Dubai Miami",
                  "Dubai Milano",
                  "DXB",
                  "DXB Jumeirah",
                  "Emerald",
                  "Emessa",
                  "Fairy Tale",
                  "Fairyland",
                  "Fakhama",
                  "Flair",
                  "Fresh Iris",
                  "Gentle Oud",
                  "Gold Noir",
                  "Hamsat Gharam",
                  "Hamsat Ghazal",
                  "Hamsat Hob",
                  "Hamsat Ishq",
                  "Harmony",
                  "Heritage",
                  "Hikaya",
                  "Hilm",
                  "Icon",
                  "Infina",
                  "Italian Leather",
                  "Jawhara Black",
                  "Jawhara Rouge",
                  "Joy",
                  "Khateer",
                  "Khayal",
                  "Khayyal",
                  "Kiss My Lips",
                  "Larimar",
                  "Leo",
                  "Librae",
                  "Lily",
                  "Lolita",
                  "Lumiere",
                  "Luna",
                  "Magic Night",
                  "Masterpiece",
                  "Milky Way",
                  "Mohra",
                  "Nada",
                  "Never Forget Me",
                  "Night in Paris",
                  "Oh Honey!",
                  "Omniya",
                  "Oscar",
                  "Patchouli with Love",
                  "Petra",
                  "Pink Crush",
                  "Qamar",
                  "Red Velvet",
                  "Rey",
                  "Rose",
                  "Rose Honey",
                  "Rose Musk",
                  "Rose Oud",
                  "Rose Vanilla",
                  "Rosé Absolute",
                  "Rosé Bouquet",
                  "Rubellite",
                  "Silver Elixer",
                  "Soirée",
                  "Soudfa",
                  "Sunset in Capri",
                  "Throne",
                  "Throne Eclipse",
                  "Timeless",
                  "Tornado",
                  "Trophy",
                  "Turath",
                  "Turath Malaki",
                  "Vanilla Rouge",
                  "Vanilla Seduction",
                  "Vision",
                  "Wadi",
                  "Whisper",
                  "Wood Intense",
                  "Zenobia"
        ]
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        self.assertEqual(len(expected), 116)
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(name, products)
        self.assertEqual(len(products), 119)
        for name in ("Love Key", "Plot Twist", "Unsolved Mystery"):
            with self.subTest(name=name):
                product = products[name]
                self.assertEqual(product.get("formats_ml"), [100])
                variant = next(
                    row for row in CATALOG.get("variants", [])
                    if row.get("product_id") == product["product_id"]
                )
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")

    def test_maison_asrar_black_grapefruit_is_a_display_alias_of_black(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        self.assertNotIn("Black Grapefruit", products)
        self.assertIn("Black Grapefruit", products["Black"].get("aliases", []))
        variant = next(
            row for row in CATALOG.get("variants", [])
            if row.get("product_id") == products["Black"]["product_id"]
        )
        self.assertEqual(variant.get("size_ml"), 100)
        self.assertIn("Black Grapefruit 100 ml", variant.get("aliases", []))


    def test_khadlaj_official_perfume_spray_visible_products_and_variants(self):
        expected = {
                  "Panache Angel Dust": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Icon": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Sawaar Vanille Blanc": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Island Dreams": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Onyx Silver": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Strawberry Shake": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Nuha Bon Bon": [
                            85,
                            "Eau de Parfum"
                  ],
                  "Oud Pure Oud Barakat": [
                            60,
                            "Eau de Parfum"
                  ],
                  "Nafais Magrib": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Oud Pure Oud Galazaid": [
                            60,
                            "Eau de Parfum"
                  ],
                  "Onyx Gold": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Oud Pure Oud Jumeirah": [
                            60,
                            "Eau de Parfum"
                  ],
                  "Shiyaaka Snow": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Ria": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Peach Velvet": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Titan": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Mansion": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Shiyaaka Shadow": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Nafais Sharq": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Island Vanilla Dunes": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Oud Pour Leather": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Cloud Candy": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Hareem Al Sultan": [
                            75,
                            "Eau de Parfum"
                  ],
                  "Island": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Private Blend Tobac Extra": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Nuha Cherry Blush": [
                            85,
                            "Eau de Parfum"
                  ],
                  "Nuha Vanilla Pearl": [
                            85,
                            "Eau de Parfum"
                  ],
                  "Azure Velvet": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Cream Velvet": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Maison L'Imaginaire": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Caffe Latte": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Saqr Al Badiya": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Opus Reborn": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Musk Pour Amber": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Fursan Brown": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Fursan White": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Sara": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Musk Pure Musk Blend": [
                            60,
                            "Eau de Parfum"
                  ],
                  "Le Prestige King": [
                            100,
                            "Eau de Parfum"
                  ],
                  "The Proposal Date Night": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Le Prestige Royal": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Le Prestige Empress": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Le Prestige Bold": [
                            100,
                            "Eau de Parfum"
                  ],
                  "The Proposal Special Occasion": [
                            100,
                            "Eau de Parfum"
                  ],
                  "25 Experience": [
                            100,
                            "Eau de Parfum"
                  ],
                  "25 Trust": [
                            100,
                            "Eau de Parfum"
                  ],
                  "25 Loyalty": [
                            100,
                            "Eau de Parfum"
                  ],
                  "25 Heritage": [
                            100,
                            "Eau de Parfum"
                  ],
                  "25 Integrity": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Valor Mystique": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Valor Honor": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Valor Chivalry": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Valor Enigma": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Empire Victor": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Empire Empress": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Empire Crown": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Empire Regent": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Karus Blu Spice": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Karus Secret Musk": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Karus Oud Fire": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Karus Amber Gold": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Maison Creation De Reve": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Maison Epoque Artistique": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Maison L'Or Noir": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Maison Flor Oud": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Wild Indonesian Oud": [
                            60,
                            "Eau de Parfum"
                  ],
                  "Mystical Indian Oud Pure": [
                            60,
                            "Eau de Parfum"
                  ],
                  "Oud Pour Klassik": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Oud Pour Noble": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Musk Pour Narcis": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Oud Pour Shaikh": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Oud Pour Rouge": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Oud Pour Blueberry": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Infini Absolute": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Cashmere Warm Oud": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Cashmere Sunshine Musk": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Oud Noir": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Sensuous Night": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Ombre Notes": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Ghadeer Silver": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Musk Al Sabah": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Oud Al Sabah": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Magnate Noble": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Magnate Premier": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Infini": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Shahi Oud": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Barwaaz Solid Grey": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Rose Couture": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Musk Couture": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Private Blend Musk Ice": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Biscotti Caramel Pop": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Biscotti Date Toffee": [
                            100,
                            "Extrait de Parfum"
                  ],
                  "Zayaan Gold": [
                            100,
                            "Eau de Parfum"
                  ],
                  "La Fede Celebrity Fame": [
                            100,
                            "Eau de Parfum"
                  ],
                  "La Fede Celebrity Crush": [
                            100,
                            "Eau de Parfum"
                  ],
                  "Ihthiraam": [
                            60,
                            "Extrait de Parfum"
                  ]
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Khadlaj"
        }
        variants = CATALOG.get("variants", [])
        self.assertEqual(len(expected), 96)
        for name, (size_ml, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product.get("concentration"), concentration)
                self.assertIn(size_ml, product.get("formats_ml", []))
                matches = [
                    row for row in variants
                    if row.get("product_id") == product["product_id"]
                    and row.get("size_ml") == size_ml
                    and row.get("concentration") == concentration
                ]
                self.assertEqual(len(matches), 1)

    def test_khadlaj_new_private_blend_tobac_extra_is_a_distinct_product(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Khadlaj"
        }
        self.assertIn("Private Blend", products)
        self.assertIn("Private Blend Tobac Extra", products)
        self.assertNotEqual(
            products["Private Blend"]["product_id"],
            products["Private Blend Tobac Extra"]["product_id"],
        )
        self.assertEqual(
            products["Private Blend Tobac Extra"].get("source_url"),
            "https://khadlaj-perfumes.com/collections/perfumes-spray/products/private-blend-tobac-extra-extrait-de-parfum-100-ml-for-men",
        )

    def test_khadlaj_sensuos_night_is_spelling_alias(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Khadlaj"
        }
        self.assertIn("Sensuos Night", products["Sensuous Night"].get("aliases", []))

if __name__ == "__main__":
    unittest.main()
