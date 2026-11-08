"""Regression guard for the user-requested fragrance brand coverage."""
import json
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
    "Maison Asrar": 125,
    "Khadlaj": 116,
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


    def test_mykonos_official_travel_size_page_has_18_explicit_15ml_variants(self):
        travel_url = "https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml"
        expected = (
            "Dark Secret", "Musk Aura", "Sansa", "Satin Blanc", "Sparkling Rosé",
            "Black Opera", "Moroccan Vanilla", "Affair", "Utopia", "Tea Poetry",
            "Hawaiian Crush", "On The Rocks", "Royal Ispahan", "Crimson",
            "California", "California Blue", "Penthouse", "Monaco Royale",
        )
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        variants = CATALOG.get("variants", [])
        self.assertEqual(len(expected), 18)
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertIn(15, row.get("formats_ml", []))
                matching = [
                    v for v in variants
                    if v.get("product_id") == row["product_id"] and v.get("size_ml") == 15
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("source_evidence_url"), travel_url)
                self.assertNotIn("concentration", matching[0])




    def test_mykonos_reconciled_catalog_has_99_identities_and_102_variants(self):
        products = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        ]
        product_ids = {row["product_id"] for row in products}
        variants = [
            row for row in CATALOG.get("variants", [])
            if row.get("product_id") in product_ids
        ]
        self.assertEqual(len(products), 99)
        self.assertEqual(len({row.get("canonical_name") for row in products}), 99)
        self.assertEqual(len(variants), 102)
        self.assertEqual(sum(row.get("size_ml") == 15 for row in variants), 18)

    def test_mykonos_new_cross_source_identities_have_provenance(self):
        expected = (
            "Adelina", "Avra Kehdabra", "Berry Caramel Pancake", "Bloody Mary",
            "Café Lyon", "Celestial", "Crystals", "Daydream", "Déjà Vu",
            "Dolce Cherry", "Eclipse", "Elysian", "Forever Musc",
            "Inception Reimagined", "Inspire Perfume", "It's Not Ella",
            "Kingsman", "Monaco Royale Black", "Nashi Pear Garden", "President",
            "Roulette", "Shape Shift", "Soft Hour x NCT Haechan", "Undercover",
            "Violette", "Wallflower", "Zeus",
        )
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        self.assertTrue(set(expected).issubset(products))
        for name in expected:
            with self.subTest(name=name):
                row = products[name]
                self.assertTrue(row.get("source_url"))
                self.assertIn(row.get("identity_status"), {"source_verified_name", "source_listed_name"})
        legacy = ("Adelina", "Bloody Mary", "Crystals", "Eclipse", "It's Not Ella",
                  "Nashi Pear Garden", "Roulette", "Zeus")
        variants = CATALOG.get("variants", [])
        for name in legacy:
            with self.subTest(legacy=name):
                product_id = products[name]["product_id"]
                self.assertEqual(products[name].get("identity_status"), "source_listed_name")
                self.assertFalse(any(v.get("product_id") == product_id for v in variants))

    def test_mykonos_new_variants_have_variant_level_source_evidence(self):
        expected = {
            "Avra Kehdabra": (100, "Eau de Parfum"),
            "Berry Caramel Pancake": (50, "Eau de Parfum"),
            "Daydream": (100, "Extrait de Parfum"),
            "Dolce Cherry": (50, "Extrait de Parfum"),
            "Forever Musc": (100, "Eau de Parfum"),
            "Inception Reimagined": (100, "Extrait de Parfum"),
            "Monaco Royale Black": (50, "Extrait de Parfum"),
            "Shape Shift": (100, "Extrait de Parfum"),
            "Soft Hour x NCT Haechan": (100, "Extrait de Parfum"),
            "Violette": (100, "Eau de Parfum"),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        variants = CATALOG.get("variants", [])
        expected_rows = 11
        found = []
        for name, (size_ml, concentration) in expected.items():
            with self.subTest(name=name):
                product = products[name]
                matching = [
                    v for v in variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == size_ml
                    and v.get("concentration") == concentration
                ]
                if name == "Monaco Royale Black":
                    matching = [
                        v for v in variants
                        if v.get("product_id") == product["product_id"]
                        and v.get("size_ml") in (50, 100)
                        and v.get("concentration") == concentration
                    ]
                    self.assertEqual({v.get("size_ml") for v in matching}, {50, 100})
                else:
                    self.assertEqual(len(matching), 1)
                for variant in matching:
                    self.assertEqual(variant.get("source_evidence_url"), product.get("source_url"))
                    found.append(variant)
        self.assertEqual(len(found), expected_rows)

    def test_mykonos_empire_x_rrq_and_imperium_are_distinct_official_products(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        empire = products["Empire x RRQ"]
        imperium = products["Imperium"]
        self.assertNotEqual(empire["product_id"], imperium["product_id"])
        self.assertEqual(empire.get("source_url"),
                         "https://officialmykonos.com/products/mykonos-x-rrq-empire-extrait-de-parfum-50ml-100ml")
        self.assertEqual(imperium.get("source_url"),
                         "https://officialmykonos.com/products/mykonos-imperium-extrait-de-parfum-100ml")
        self.assertIn("Empire", empire.get("aliases", []))
        self.assertNotIn("Imperium", empire.get("aliases", []))
        self.assertEqual(
            {v.get("size_ml") for v in CATALOG.get("variants", [])
             if v.get("product_id") == empire["product_id"]},
            {50, 100},
        )
        self.assertEqual(
            {v.get("size_ml") for v in CATALOG.get("variants", [])
             if v.get("product_id") == imperium["product_id"]},
            {100},
        )




    def test_mykonos_source_name_variants_are_aliases_not_duplicate_products(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        expected_aliases = {
            "California": "California Signature",
            "Jynx": "Jinx",
            "Nautilus": "Nautilius",
            "Shades Perfume": "Shades Parfum",
            "Affair": "Intimate Affair",
            "Xoxo Rosy": "XoXo, Rosy",
        }
        for canonical, alias in expected_aliases.items():
            with self.subTest(canonical=canonical, alias=alias):
                self.assertIn(canonical, products)
                self.assertIn(alias, products[canonical].get("aliases", []))
        canonical_names = [str(row.get("canonical_name", "")).casefold() for row in products.values()]
        self.assertEqual(len(canonical_names), len(set(canonical_names)))


    def test_maison_asrar_cross_source_variants_and_identity_cleanup(self):
        expected_sizes = {
            "Belgravia": 100,
            "Legacy": 100,
            "Vanguard": 100,
            "Regent": 100,
            "Ameer": 100,
            "Majesty": 100,
            "Veyra": 100,
            "Vanilla Aura": 100,
            "Faris Al Arab": 100,
            "Vanilla Voyage": 25,
            "III Thriller": 100,
            "Last Swim": 100,
            "Pomme Rouge": 100,
            "Haven": 100,
            "Muharib": 100,
            "Silent Surge": 100,
            "Treasure": 100,
            "Hunter": 100,
            "Imperial": 100,
            "Monarch": 100,
            "1963": 100,
            "Adorable": 100,
            "Alonoud": 100,
            "Basma": 100,
            "Black": 100,
            "Bloom Bloom": 100,
            "Bonita": 100,
            "Casablanca": 100,
            "Cascade": 100,
            "Coffee Blend": 100,
            "Daham": 100,
            "Date Night": 100,
            "Dear Jasmine": 100,
            "Desire": 100,
            "Dubai London": 100,
            "Dubai Miami": 100,
            "Dubai Milano": 100,
            "DXB": 100,
            "DXB Jumeirah": 100,
            "Emerald": 110,
            "Fairy Tale": 100,
            "Fakhama": 100,
            "Flair": 100,
            "Fresh Iris": 100,
            "Gentle Oud": 80,
            "Gold Noir": 110,
            "Hamsat Gharam": 100,
            "Hamsat Ghazal": 100,
            "Hamsat Hob": 100,
            "Hamsat Ishq": 100,
            "Heritage": 100,
            "Hikaya": 100,
            "Hilm": 100,
            "Icon": 100,
            "Infina": 100,
            "Italian Leather": 80,
            "Jawhara Black": 100,
            "Jawhara Rouge": 100,
            "Joy": 100,
            "Khateer": 100,
            "Khayal": 100,
            "Kiss My Lips": 90,
            "Leo": 100,
            "Librae": 100,
            "Lily": 100,
            "Lolita": 100,
            "Lumiere": 110,
            "Luna": 100,
            "Magic Night": 100,
            "Masterpiece": 100,
            "Milky Way": 100,
            "Nada": 100,
            "Never Forget Me": 90,
            "Night in Paris": 90,
            "Oh Honey!": 100,
            "Oscar": 100,
            "Patchouli with Love": 100,
            "Petra": 100,
            "Pink Crush": 100,
            "Red Velvet": 100,
            "Rey": 100,
            "Rose": 110,
            "Rose Honey": 100,
            "Rose Musk": 100,
            "Rose Oud": 100,
            "Rose Vanilla": 100,
            "Rosé Absolute": 100,
            "Rosé Bouquet": 100,
            "Silver Elixer": 110,
            "Soirée": 100,
            "Soudfa": 100,
            "Sunset in Capri": 90,
            "Throne": 100,
            "Throne Eclipse": 100,
            "Timeless": 100,
            "Tornado": 100,
            "Trophy": 100,
            "Turath": 100,
            "Turath Malaki": 100,
            "Vanilla Rouge": 100,
            "Vanilla Seduction": 100,
            "Vision": 100,
            "Wadi": 100,
            "Wood Intense": 80,
            "Zenobia": 100,
        }
        edp_names = {"Belgravia", "Legacy", "Vanguard", "Regent", "Ameer", "Majesty", "Veyra", "Vanilla Aura", "Faris Al Arab", "Vanilla Voyage", "III Thriller", "Last Swim", "Pomme Rouge", "Haven", "Muharib", "Silent Surge", "Treasure", "Hunter", "Imperial", "Monarch", "Bonita", "Cascade", "Coffee Blend", "Daham", "Date Night", "Dubai London", "Dubai Miami", "Dubai Milano", "DXB", "DXB Jumeirah", "Fakhama", "Flair", "Gentle Oud", "Gold Noir", "Hamsat Ishq", "Heritage", "Hikaya", "Hilm", "Infina", "Italian Leather", "Joy", "Khateer", "Khayal", "Kiss My Lips", "Leo", "Librae", "Lily", "Lolita", "Lumiere", "Luna", "Masterpiece", "Milky Way", "Nada", "Never Forget Me", "Night in Paris", "Oh Honey!", "Patchouli with Love", "Pink Crush", "Red Velvet", "Rose", "Silver Elixer", "Soirée", "Throne", "Throne Eclipse", "Timeless", "Tornado", "Vanilla Seduction", "Vision", "Wadi", "Wood Intense"}
        products = {row.get("canonical_name"): row for row in CATALOG.get("products", []) if row.get("brand_name") == "Maison Asrar"}
        variants = CATALOG.get("variants", [])
        self.assertEqual(len(products), 125)
        self.assertNotIn("Black Grapefruit", products)
        self.assertEqual(len([v for v in variants if v.get("product_id") in {p["product_id"] for p in products.values()}]), 113)
        guide_variants = [v for v in variants if v.get("source_evidence_url") == "https://maisonasrarperfumes.eu/perfumes/"]
        self.assertEqual(len(guide_variants), 105)
        self.assertEqual(sum(v.get("concentration") == "Eau de Parfum" for v in guide_variants), 70)
        self.assertEqual(sum("concentration" not in v for v in guide_variants), 35)

        self.assertIn("Rosé", products["Rose"].get("aliases", []))
        self.assertIn("Silver Elixir", products["Silver Elixer"].get("aliases", []))
        for name, size in expected_sizes.items():
            with self.subTest(name=name):
                row = products[name]
                self.assertIn(size, row.get("formats_ml", []))
                matching = [v for v in variants if v.get("product_id") == row["product_id"] and v.get("size_ml") == size]
                self.assertEqual(len(matching), 1)
                if name in edp_names:
                    self.assertEqual(row.get("concentration"), "Eau de Parfum")
                    self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
        for name in ["Shaheen Black"]:
            with self.subTest(legacy_name=name):
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_listed_name")
                self.assertFalse(any(v.get("product_id") == row["product_id"] for v in variants))


    def test_maison_asrar_retailer_confirmed_variants_have_exact_evidence(self):
        expected = {
            "Amal": ("https://thealternativebeauty.co.uk/product/maison-asrar-amal-eau-de-parfum-100ml/", "VAR-SH-MAISON-ASRAR-AMAL-100"),
            "Asala": ("https://youshahperfumes.co.uk/product/asala-eau-de-parfum-100ml/", "VAR-SH-MAISON-ASRAR-ASALA-100"),
            "Red Carpet": ("https://shop-gulforchid.com/products/red-carpet", "VAR-SH-MAISON-ASRAR-RED-CARPET-100"),
            "Runway Girl": ("https://shop-gulforchid.com/products/runway-girl", "VAR-SH-MAISON-ASRAR-RUNWAY-GIRL-100"),
            "Smokey Eyes": ("https://shop-gulforchid.com/products/smokey-eyes", "VAR-SH-MAISON-ASRAR-SMOKEY-EYES-100"),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, variant_id) in expected.items():
            with self.subTest(name=name):
                product = products[name]
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                matching = [v for v in variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("variant_id"), variant_id)
                self.assertEqual(matching[0].get("size_ml"), 100)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(matching[0].get("source_evidence_url"), source_url)

    def test_maison_asrar_every_variant_has_source_evidence(self):
        product_ids = {
            row["product_id"] for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        variants = [v for v in CATALOG.get("variants", []) if v.get("product_id") in product_ids]
        self.assertEqual(len(variants), 113)
        self.assertTrue(all(v.get("source_evidence_url") for v in variants))

    def test_maison_asrar_shaheen_black_remains_name_only(self):
        row = next(
            p for p in CATALOG.get("products", [])
            if p.get("brand_name") == "Maison Asrar" and p.get("canonical_name") == "Shaheen Black"
        )
        self.assertEqual(row.get("identity_status"), "source_listed_name")
        self.assertEqual(row.get("source_url"), "https://www.fragrantica.com/designers/MAISON-ASRAR.html")
        self.assertNotIn("formats_ml", row)
        self.assertNotIn("concentration", row)
        self.assertFalse(any(v.get("product_id") == row["product_id"] for v in CATALOG.get("variants", [])))


if __name__ == "__main__":
    unittest.main()
