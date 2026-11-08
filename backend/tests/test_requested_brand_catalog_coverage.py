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
    "Mykonos": 98,
    "Maison Asrar": 125,
    "Khadlaj": 166,
    "Bujairami": 353,
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


    def test_velixir_official_catalog_has_28_fragrances_and_24_edp_variant_pairs(self):
        velixir = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Velixir"
        }
        expected_edp = {
            "Adonis", "Aphrodite", "Apollo", "Ares", "Artemis", "Asteria",
            "Athena", "Concordia", "Demeter", "Galatea", "Harmonia", "Helios",
            "Hera", "Himeros", "Icarus", "Morpheus", "Narcisus", "Nyx",
            "Orion", "Paladin", "Persephone", "Poseidon", "Selene", "Uranus",
        }
        expected_extrait = {"Comus", "Ether", "Orpheus", "Panacea"}
        self.assertEqual(set(velixir), expected_edp | expected_extrait)
        variants = CATALOG.get("variants", [])
        for name in expected_edp:
            with self.subTest(name=name):
                row = velixir[name]
                self.assertEqual(row.get("concentration"), "Eau de Parfum")
                self.assertEqual(row.get("formats_ml"), [35, 100])
                self.assertTrue(row.get("source_url", "").startswith("https://velixirparfums.com/products/"))
                product_variants = [
                    variant for variant in variants
                    if variant.get("product_id") == row.get("product_id")
                ]
                self.assertEqual(
                    {(variant.get("size_ml"), variant.get("concentration")) for variant in product_variants},
                    {(35, "Eau de Parfum"), (100, "Eau de Parfum")},
                )
        for name in expected_extrait:
            with self.subTest(name=name):
                row = velixir[name]
                self.assertEqual(row.get("concentration"), "Extrait de Parfum")
                self.assertTrue(row.get("source_url", "").startswith("https://velixirparfums.com/products/"))


    def test_maison_asrar_fragrantica_additions_and_silver_elixir_alias(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        expected = {
            "Asala": (
                "https://www.divaparfum.com/shop/eau-de-parfum-asala-100ml-maison-asrar-17964",
                "source_listed_name",
            ),
            "Amal": (
                "https://nufaar.com/gb/en/products/maison-asrar-amal",
                "source_listed_name",
            ),
            "Red Carpet": (
                "https://shop-gulforchid.com/products/red-carpet",
                "source_verified_name",
            ),
            "Runway Girl": (
                "https://shop-gulforchid.com/products/runway-girl",
                "source_verified_name",
            ),
            "Smokey Eyes": (
                "https://shop-gulforchid.com/products/smokey-eyes",
                "source_verified_name",
            ),
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, status) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("identity_status"), status)
                self.assertEqual(row.get("formats_ml"), [100])
                self.assertEqual(row.get("concentration"), "Eau de Parfum")
                matching = [
                    variant for variant in variants
                    if variant.get("product_id") == row.get("product_id")
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("size_ml"), 100)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
        self.assertIn("Silver Elixir", products["Silver Elixer"].get("aliases", []))


    def test_khadlaj_official_store_and_fragrantica_reconciliation_additions(self):
        expected = {
            "Bleu Glace": (100, "Extrait de Parfum"),
            "Code Viola Nectar": (100, "Eau de Parfum"),
            "Desert Rose": (100, "Extrait de Parfum"),
            "Gaith": (100, "Eau de Parfum"),
            "Johayna Green": (20, "Perfume Oil"),
            "Kayaan Gold": (20, "Perfume Oil"),
            "Maya": (20, "Perfume Oil"),
            "Mocha Latte": (100, "Extrait de Parfum"),
            "Nuha": (85, "Eau de Parfum"),
            "Opulence Bleu": (100, "Eau de Parfum"),
            "Pink Musk": (20, "Perfume Oil"),
            "Purple Musk": (20, "Perfume Oil"),
            "Rasayel Shagaf": (100, "Eau de Parfum"),
            "Rasayel Vid": (100, "Eau de Parfum"),
            "Rose & Romance": (100, "Eau de Parfum"),
            "Uno Sensuale": (100, "Eau de Parfum"),
            "Wow Oud": (100, "Eau de Parfum"),
            "Biscotti Melon Misk": (100, "Extrait de Parfum"),
            "Hareem Al Sultan Blue": (35, "Perfume Oil"),
            "Hareem Al Sultan Silver": (35, "Perfume Oil"),
            "Aaliya": (27, "Perfume Oil"),
            "Al Riyan": (17, "Perfume Oil"),
            "Alf Wardaat": (30, "Perfume Oil"),
            "Amber Pure": (20, "Perfume Oil"),
            "Anabia Blue": (20, "Perfume Oil"),
            "Anabia Red": (20, "Perfume Oil"),
            "Arabian Treasure": (20, "Perfume Oil"),
            "Azaari": (17, "Perfume Oil"),
            "Ghazlaan": (20, "Perfume Oil"),
            "Haneen Gold": (20, "Perfume Oil"),
            "Ibhaar": (18, "Perfume Oil"),
            "Jameel": (25, "Perfume Oil"),
            "Malika Red": (20, "Perfume Oil"),
            "Oud & Musk": (20, "Perfume Oil"),
            "Raniya": (18, "Perfume Oil"),
            "Rimaal Brown": (15, "Perfume Oil"),
            "Roohi Wa Roohak Gold": (20, "Perfume Oil"),
            "Shamookh Gold": (20, "Perfume Oil"),
            "Shamookh Silver": (20, "Perfume Oil"),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Khadlaj"
        }
        variants = CATALOG.get("variants", [])
        for name, (size_ml, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertIn(size_ml, row.get("formats_ml", []))
                matching = [
                    variant for variant in variants
                    if variant.get("product_id") == row.get("product_id")
                    and variant.get("size_ml") == size_ml
                    and variant.get("concentration") == concentration
                ]
                self.assertEqual(len(matching), 1)
        pure = products["Pure Musk"]
        self.assertEqual(
            {(v.get("size_ml"), v.get("concentration")) for v in variants if v.get("product_id") == pure["product_id"]},
            {(20, "Perfume Oil")},
        )
        pure_edp = products["Pure Musk EDP"]
        self.assertEqual(
            {(v.get("size_ml"), v.get("concentration")) for v in variants if v.get("product_id") == pure_edp["product_id"]},
            {(100, "Eau de Parfum")},
        )
        self.assertIn("Ana Wa Anta", products)
        self.assertIn("Musk Ice", products["Private Blend Musk Ice"].get("aliases", []))
        self.assertIn("Creation De Reve", products["Maison Creation De Reve"].get("aliases", []))
        self.assertIn("Epoque Artistique", products["Maison Epoque Artistique"].get("aliases", []))
        self.assertIn("Flor Oud", products["Maison Flor Oud"].get("aliases", []))
        self.assertIn("L'Imaginaire", products["Maison L'Imaginaire"].get("aliases", []))
        self.assertIn("L'Or Noir", products["Maison L'Or Noir"].get("aliases", []))
        for name in ("D'Love", "Barwaaz Pure Navy", "Ghadeer Gold", "Vanilla Kiss", "Lulu Al Khaleej", "Nagham", "Rasha", "Safari Gold"):
            self.assertIn(name, products)


    def test_all_147_fragrantica_khadlaj_names_are_covered_by_canonical_names_or_aliases(self):
        def normalize(value):
            value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
            return re.sub(r"[^a-z0-9]", "", value.casefold())

        khadlaj = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Khadlaj"
        ]
        searchable = {
            normalize(name)
            for row in khadlaj
            for name in [row.get("canonical_name"), *(row.get("aliases") or [])]
            if name
        }
        fragrantica_names = [
          "Bleu Glace",
          "Caffe Latte",
          "Cashmere Sunshine Musk",
          "Cashmere Warm Oud",
          "Cloud Candy",
          "Code Viola Nectar",
          "D'Love",
          "Desert Rose",
          "Gaith",
          "Icon",
          "Ihthiraam",
          "Johayna Green",
          "Kayaan Gold",
          "Magnate Noble",
          "Mansion",
          "Maya",
          "Mocha Latte",
          "Muse",
          "Musk Al Sabah",
          "Musk Ice",
          "Musk Pour Amber",
          "Musk Pour Narcis",
          "Ombre Notes",
          "Opulence Bleu",
          "Oud Noir",
          "Pink Musk",
          "Pure Musk",
          "Purple Musk",
          "Qarar",
          "Rasayel Shagaf",
          "Rasayel Vid",
          "Ria",
          "Rose & Romance",
          "Rose Couture",
          "Sara",
          "Sawaar Vanille Blanc",
          "Sensuous Night",
          "Shiyaaka White",
          "Strawberry Shake",
          "Sueno",
          "The Proposal Date Night",
          "Titan",
          "Uno Sensuale",
          "Vanilla Kiss",
          "Wow Oud",
          "Zayaan Gold",
          "Zayaan Silver",
          "Barwaaz Pure Navy",
          "Barwaaz Solid Grey",
          "Biscotti Caramel Pop",
          "Biscotti Date Toffee",
          "Biscotti Melon Misk",
          "Empire Crown",
          "Empire Regent",
          "Empire Victor",
          "Fursan Brown",
          "Fursan White",
          "Ghadeer Gold",
          "Ghadeer Silver",
          "Hareem Al Sultan",
          "Hareem Al Sultan Blue",
          "Hareem Al Sultan Gold",
          "Hareem Al Sultan Silver",
          "Infini",
          "Infini Absolute",
          "Island",
          "Island Dreams",
          "Island Sun",
          "Island Vanilla Dunes",
          "Karus Amber Gold",
          "Karus Blu Spice",
          "Karus Gold Absolu",
          "Karus Oud Fire",
          "Karus Secret Musk",
          "Khadlaj 25 Experience",
          "Khadlaj 25 Heritage",
          "Khadlaj 25 Integrity",
          "Khadlaj 25 Loyalty",
          "Khadlaj 25 Trust",
          "Le Prestige Bold",
          "Le Prestige Empress",
          "Le Prestige King",
          "Le Prestige Royal",
          "Creation De Reve",
          "Epoque Artistique",
          "Flor Oud",
          "L'imaginaire",
          "L'Or Noir",
          "Musk Pure Musk Blend",
          "Mystical Indian Oud Pure",
          "Oud Pure Oud Barakat",
          "Oud Pure Oud Galazaid",
          "Oud Pure Oud Jumeirah",
          "Wild Indonesian Oud",
          "Nafais Magrib",
          "Nafais Sharq",
          "Nuha",
          "Nuha Bon Bon",
          "Nuha Cherry Blush",
          "Nuha Vanilla Pearl",
          "Onyx Galaxy",
          "Onyx Gold",
          "Onyx Silver",
          "Oud Pour Blueberry",
          "Oud Pour Klassik",
          "Panache Angel Dust",
          "Panache Eleganza",
          "Shiyaaka Blue",
          "Shiyaaka For Men",
          "Shiyaaka Gold",
          "Shiyaaka Rose Gold",
          "Shiyaaka Shadow",
          "Shiyaaka Sky",
          "Shiyaaka Snow",
          "Stellar Musk",
          "Stellar Oud",
          "Valor Chivalry",
          "Valor Enigma",
          "Valor Honor",
          "Valor Mystique",
          "Azure Velvet",
          "Cream Velvet",
          "Peach Velvet",
          "Aaliya",
          "Al Riyan",
          "Alf Wardat",
          "Amber Pure",
          "Ana Wa Anta",
          "Anabia Blue",
          "Anabia Red",
          "Arabian Treasure",
          "Azaari",
          "Ghazlaan",
          "Haneen Gold",
          "Ibhaar",
          "Jameel",
          "Lulu Al Khaleej",
          "Malika Red",
          "Nagham",
          "Oud & Musk",
          "Raniya",
          "Rasha",
          "Rimaal Brown",
          "Roohi Wa Roohak Gold",
          "Safari Gold",
          "Shamookh Gold",
          "Shamookh Silver"
]
        missing = [
            name for name in fragrantica_names
            if normalize(name) not in searchable
        ]
        self.assertEqual(len(fragrantica_names), 147)
        self.assertEqual(missing, [])


    def test_bujairami_range_names_0_to_c_are_all_catalogued(self):
        def normalize(value):
            value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
            return re.sub(r"[^a-z0-9]", "", value.casefold())

        expected = [
          "10/10",
          "2000",
          "22",
          "25",
          "26",
          "29",
          "33",
          "50 Shades",
          "A La Carte",
          "Above The Clouds",
          "Absolute Power",
          "Abyss",
          "Ace",
          "Addiction",
          "Adore",
          "Adversary",
          "Aethera",
          "Affectionate",
          "Affinity",
          "After Dark",
          "After Light",
          "Afterglow",
          "Afternoon Bliss",
          "Aftershock",
          "Agha",
          "Ahla Sabiyeh",
          "Air Affair",
          "Airborne",
          "Airy Oud",
          "Al Waad",
          "Alpha",
          "Altitude",
          "Amaretto",
          "Amazing",
          "Amazing Night",
          "Amber Eclipse",
          "Amber Floweret",
          "Amber Grove",
          "Amber Hills",
          "Amira",
          "Amoura",
          "Amplify",
          "Aoud Mineral",
          "Apex",
          "Apple Crumble",
          "Aqua Dew",
          "Aqua Infinite",
          "Aqua Prevail",
          "Aqua Pure",
          "Aqua Rush",
          "Aqua Surge",
          "Aquafina",
          "Aquaman",
          "Arabian Brew",
          "Arabian Gold",
          "Arabian Love",
          "Arabian Valley",
          "Arizona",
          "Artistic Lady",
          "Ascension",
          "Asfahan Oud",
          "Assassin",
          "Astral",
          "Astro",
          "At Last",
          "Aurora",
          "Aussie Glow",
          "Australian Tonka",
          "Australian Watermelon",
          "Baccarat Oud",
          "Backstage",
          "Bad N Boujee",
          "Bad Obsession",
          "Bad Romance",
          "Baddie",
          "Bahebak",
          "Baked Bliss",
          "Ballerina",
          "Banana Booz",
          "Banger",
          "Bare Oud",
          "Barrel Breeze",
          "Be Happy",
          "Beach Vibe",
          "Beast",
          "Beastmode",
          "Beautiful Lady",
          "Beauty and the Beast",
          "Bee Sting",
          "Before Sunrise",
          "Belissimo",
          "Belle",
          "Benzo",
          "Big Love",
          "Billion Dollar",
          "Billionaires Club",
          "Billionaires Club Intense",
          "Bitter Sweet",
          "Black Empire",
          "Black Reserve",
          "Black Tie",
          "Blackjack",
          "Blanc Bloom",
          "Blazing",
          "Blissful Juliet",
          "Blood Cherry",
          "Blood Suede",
          "Bloodline",
          "Bloom",
          "Blossom",
          "Blue Chill",
          "Blue Citrus",
          "Blue Fire",
          "Blue Heat",
          "Blue Knights",
          "Blue Note",
          "Blue Serenade",
          "Blue Steel",
          "Blue Voyage",
          "Blue Water",
          "Blush",
          "Blush Milk",
          "Bohemien",
          "Bombshell",
          "Bonfire",
          "Booz",
          "Booz Extreme",
          "Born Nomad",
          "Boss Lady",
          "Boss Life",
          "Boss Life Extreme",
          "Bossman",
          "Bottled Island",
          "Bottled Paradise",
          "Bottled Red City",
          "Boujee",
          "Boujee Oud",
          "Boundless",
          "Bravo",
          "Breathless",
          "Breezy",
          "Bright Essence",
          "Brumbie",
          "Burn Slow",
          "Burning Ambition",
          "Burning Love",
          "Burnt Sugar",
          "Butter Me Up",
          "Buzzin",
          "Cafe Creme",
          "Caffe OUD",
          "Calabrian Sun",
          "Calabrian Wear",
          "Candlewood",
          "Candy Carousel",
          "Candy Crush",
          "Candyland",
          "Captivating",
          "Caramel Drift",
          "Caramelle",
          "Carnival",
          "Cartel",
          "Casablanca",
          "Casanova",
          "Cascade",
          "Catch Me At Sunset",
          "Cavalier",
          "Centre Stage",
          "Chai Time",
          "Chamber",
          "Charmed",
          "Chasing Sunsets",
          "Check Mate",
          "Cheeky Drizzle",
          "Cheeky Pash",
          "Cherry Berry",
          "Cherry Cherry Lady",
          "Cherry Fever",
          "Cherry Lightning",
          "Cherry Reign",
          "Cherry Riot",
          "Chic Star",
          "Chic Wood",
          "Choco Oud",
          "Chosen",
          "Chosen One",
          "Chroma",
          "Chubby",
          "Cinder Kiss",
          "CinnaMan",
          "Citrus Breeze",
          "Citrus Fever",
          "Citrus Mirage",
          "Citrus Spark",
          "Citrusa",
          "City Life",
          "Clara Belle",
          "Classic Life",
          "Classy",
          "Clean Slate",
          "Cloud Kiss",
          "Cloud Nine",
          "Clubs",
          "Coastal Mist",
          "Cobra Kiss",
          "Coco Crazy",
          "Coco Dream",
          "Coconara",
          "Codebreaker",
          "Cold Crush",
          "Confessions",
          "Confessions Absolu",
          "Confetti Kisses",
          "Cookies and Cream",
          "Copa Nova",
          "Copacabana Crush",
          "Coral",
          "Cosmic",
          "Countess",
          "Cracka",
          "Crave",
          "Crazy in Love",
          "Crazy Mango",
          "Cream & Crave",
          "Creamy Oud Bliss",
          "Crown",
          "Crown Chai",
          "Crown of Fangs",
          "Crownwood",
          "Crying Moon",
          "Cryptic",
          "Crystal Glow",
          "Cuban Nights",
          "Cyprus"
]
        products = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Bujairami"
        ]
        searchable = {
            normalize(name)
            for row in products
            for name in [row.get("canonical_name"), *(row.get("aliases") or [])]
            if name
        }
        missing = [name for name in expected if normalize(name) not in searchable]
        self.assertEqual(len(expected), 234)
        self.assertEqual(missing, [])

if __name__ == "__main__":
    unittest.main()
