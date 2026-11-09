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
    "Mykonos": 72,
    # Corrected 2026-11-09 after the multi-brand storefront audit moved six Gulf Orchid products out of Maison Asrar.
    "Maison Asrar": 115,
    "Khadlaj": 116,
    "Bujairami": 142,
    "Paris Corner": 245,
    "Assaf": 140,
    "Al Wataniah": 86,
    "Armaf": 191,
    "French Avenue": 119,
    "Arabiyat Prestige": 118,
    # Corrected 2026-11-09: 16 standalone Gulf Orchid identities remain after moving Maison Asrar products and removing collection labels from the old 23-row storefront harvest.
    # Corrected 2026-11-09 after six additional Gulf Orchid identities were verified on the Maison Asrar multi-brand storefront.
    "Gulf Orchid": 22,
    "Swiss Arabian": 32,
    "Games of Spades": 29,
    "Lattafa": 115,
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
            "Forbidden Fruit", "Magnetiq", "Plantine Blanc", "X Xandal",
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



    def test_armaf_uniq_oud_forever_official_detail_page_is_a_provenance_candidate(self):
        row = next(
            product for product in CATALOG.get("products", [])
            if product.get("brand_name") == "Armaf"
            and product.get("canonical_name") == "Uniq Oud Forever"
        )
        # The canonical identity already exists. A later provenance update
        # must preserve this product ID and must never append a second row.
        self.assertEqual(row.get("product_id"), "SH-ARMAF-f650f6a8")
        self.assertEqual(row.get("identity_status"), "source_listed_name")
        self.assertNotEqual(
            row.get("source_url"),
            "https://armaf.com/products/uniq-oud-forever-spr",
            "Promote only in a dedicated provenance update after page fields are rechecked.",
        )


    def test_lattafa_asad_polar_official_100ml_identity(self):
        rows = [row for row in CATALOG.get("products", []) if row.get("brand_name") == "Lattafa" and row.get("canonical_name") == "Asad Polar"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), "https://lattafa.com/product/asad-polar/")
        self.assertIn(100, row.get("formats_ml", []))
        self.assertNotIn("concentration", row)
        variants = [v for v in CATALOG.get("variants", []) if v.get("product_id") == row["product_id"]]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].get("size_ml"), 100)
        self.assertNotIn("concentration", variants[0])

    def test_lychee_musk_official_page_provenance_and_variant(self):
        rows = [row for row in CATALOG.get("products", []) if row.get("brand_name") == "Arabiyat Prestige" and row.get("canonical_name") == "Lychee Musk"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.get("product_id"), "SH-ARABIYAT-PRESTIGE-0b061839")
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), "https://arabiyatprestige.com/products/arabiyat-prestige-lychee-musk-edp-100ml-unisex")
        self.assertEqual(row.get("concentration"), "Eau de Parfum")
        matches = [v for v in CATALOG.get("variants", []) if v.get("product_id") == row["product_id"]]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].get("size_ml"), 100)
        self.assertEqual(matches[0].get("concentration"), "Eau de Parfum")
        self.assertEqual(matches[0].get("source_evidence_url"), row["source_url"])

    def test_lychee_musk_is_already_present_and_must_not_be_duplicated(self):
        rows = [
            product for product in CATALOG.get("products", [])
            if product.get("brand_name") == "Arabiyat Prestige"
            and product.get("canonical_name") == "Lychee Musk"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("product_id"), "SH-ARABIYAT-PRESTIGE-0b061839")
        self.assertEqual(rows[0].get("identity_status"), "source_verified_name")
        self.assertEqual(
            rows[0].get("source_url"),
            "https://arabiyatprestige.com/products/arabiyat-prestige-lychee-musk-edp-100ml-unisex",
        )

    def test_armaf_uniq_effects_of_uniq_has_documented_60ml_edp_variant(self):
        row = next(
            (
                product for product in CATALOG.get("products", [])
                if product.get("brand_name") == "Armaf"
                and product.get("canonical_name") == "Uniq Effects of Uniq"
            ),
            None,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        source = "https://armaf.com/products/uniq-effects-of-uniq-spr"
        self.assertEqual(row.get("source_url"), source)
        self.assertIn(60, row.get("formats_ml", []))
        matches = [
            variant for variant in CATALOG.get("variants", [])
            if variant.get("product_id") == row["product_id"]
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].get("size_ml"), 60)
        self.assertEqual(matches[0].get("concentration"), "Eau de Parfum")
        self.assertEqual(matches[0].get("source_evidence_url"), source)

    def test_afnan_kiaana_vibes_and_lynked_trio_have_official_100ml_edp_variants(self):
        expected = {
            "Kiaana Vibes": "https://www.at.afnan.com/en/products/kiaana-vibes",
            "Lynked Forever": "https://www.at.afnan.com/en/products/lynked-forever",
            "Lynked Freedom": "https://www.at.afnan.com/en/products/lynked-freedom",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Afnan"
        }
        variants = CATALOG.get("variants", [])
        for name, source in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                self.assertIn(100, row.get("formats_ml", []))
                self.assertEqual(row.get("concentration"), "Eau de Parfum")
                matching = [
                    variant for variant in variants
                    if variant.get("product_id") == row["product_id"]
                    and variant.get("size_ml") == 100
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(matching[0].get("source_evidence_url"), source)

    def test_paris_corner_molten_caramel_official_100ml_variant(self):
        rows = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
            and row.get("canonical_name") == "Molten Caramel"
        ]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        source = "https://www.pariscornerperfumes.com/products/molten-caramel"
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), source)
        self.assertIn(100, row.get("formats_ml", []))
        matching = [
            variant for variant in CATALOG.get("variants", [])
            if variant.get("product_id") == row["product_id"]
            and variant.get("size_ml") == 100
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].get("source_evidence_url"), source)
        self.assertNotIn("concentration", matching[0])

    def test_khadlaj_island_dreams_official_page_and_100ml_extrait_variant(self):
        row = next(
            (
                product for product in CATALOG.get("products", [])
                if product.get("brand_name") == "Khadlaj"
                and product.get("canonical_name") == "Island Dreams"
            ),
            None,
        )
        self.assertIsNotNone(row)
        source = "https://khadlaj-perfumes.com/products/island-dreams-100-ml-extrait-de-parfum"
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), source)
        self.assertEqual(row.get("concentration"), "Extrait de Parfum")
        self.assertIn(100, row.get("formats_ml", []))
        matches = [
            variant for variant in CATALOG.get("variants", [])
            if variant.get("product_id") == row["product_id"]
            and variant.get("size_ml") == 100
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].get("concentration"), "Extrait de Parfum")
        self.assertEqual(matches[0].get("source_evidence_url"), source)

    def test_khadlaj_onyx_galaxy_official_100ml_edp_variant(self):
        row = next(
            (
                product for product in CATALOG.get("products", [])
                if product.get("brand_name") == "Khadlaj"
                and product.get("canonical_name") == "Onyx Galaxy"
            ),
            None,
        )
        self.assertIsNotNone(row)
        source = "https://khadlaj-perfumes.com/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men"
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), source)
        self.assertEqual(row.get("concentration"), "Eau de Parfum")
        self.assertEqual(row.get("gender"), "Men")
        self.assertIn(100, row.get("formats_ml", []))
        matches = [
            variant for variant in CATALOG.get("variants", [])
            if variant.get("product_id") == row["product_id"]
            and variant.get("size_ml") == 100
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].get("concentration"), "Eau de Parfum")
        self.assertEqual(matches[0].get("source_evidence_url"), source)



    def test_mykonos_first_fifteen_products_have_individual_official_page_provenance(self):
        expected = {
            "Aphrodite": ("https://officialmykonos.com/products/mykonos-aphrodite-extrait-de-parfum-50ml-100ml", "Extrait de Parfum", (50, 100)),
            "Baby Love": ("https://officialmykonos.com/products/mykonos-baby-love-edp-50ml", "Eau de Parfum", (50,)),
            "Black Opera": ("https://officialmykonos.com/products/mykonos-black-opera-extrait-de-parfum-100ml", "Extrait de Parfum", (100,)),
            "Bonfire Vanilla": ("https://officialmykonos.com/products/mykonos-bonfire-vanilla-extrait-de-parfum-50ml", "Extrait de Parfum", (50,)),
            "Cafe Drops": ("https://officialmykonos.com/products/mykonos-cafe-drops-extrait-de-parfum-50ml", "Extrait de Parfum", (50,)),
            "California Blue": ("https://officialmykonos.com/products/mykonos-california-blue-extrait-de-parfum-50ml", "Extrait de Parfum", (50, 100)),
            "California Club": ("https://officialmykonos.com/products/mykonos-california-club-extrait-de-parfum-50ml", "Extrait de Parfum", (50,)),
            "California": ("https://officialmykonos.com/products/mykonos-california-signature-50ml", "Extrait de Parfum", (50, 100)),
            "Caramel Fudge Cookie": ("https://officialmykonos.com/products/mykonos-caramel-fudge-cookie-edp-50ml", "Eau de Parfum", (50,)),
            "Coconut Dreams": ("https://officialmykonos.com/products/mykonos-coconut-dreams-extrait-de-parfum-50ml", "Extrait de Parfum", (50,)),
            "Conquer": ("https://officialmykonos.com/products/mykonos-conquer-extrait-de-parfum-100ml", "Extrait de Parfum", (50, 100)),
            "Constantine": ("https://officialmykonos.com/products/mykonos-constantine-extrait-de-parfum-50ml", "Extrait de Parfum", (50,)),
            "Crimson": ("https://officialmykonos.com/products/mykonos-crimson-extrait-de-parfum-100ml", "Extrait de Parfum", (100,)),
            "Dark Secret": ("https://officialmykonos.com/products/mykonos-dark-secret-extrait-de-parfum-100ml", "Extrait de Parfum", (100,)),
            "Dreamscape": ("https://officialmykonos.com/products/mykonos-dreamscape-extrait-de-parfum-50ml-100ml", "Extrait de Parfum", (50, 100)),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, concentration, sizes) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("concentration"), concentration)
                matching_products = [
                    product for product in CATALOG.get("products", [])
                    if product.get("brand_name") == "Mykonos"
                    and product.get("canonical_name") == name
                ]
                self.assertEqual(len(matching_products), 1)
                self.assertEqual(row.get("product_id"), matching_products[0].get("product_id"))
                for size in sizes:
                    self.assertIn(size, row.get("formats_ml", []))
                    self.assertTrue(any(
                        variant.get("product_id") == row["product_id"]
                        and variant.get("size_ml") == size
                        and variant.get("concentration") == concentration
                        for variant in variants
                    ))


    def test_mykonos_second_fifteen_products_have_individual_official_page_provenance(self):
        expected = {
            "Enchanted": ("https://officialmykonos.com/products/mykonos-enchanted-extrait-de-parfum-50ml-100ml", (50, 100)),
            "Hawaiian Crush": ("https://officialmykonos.com/products/mykonos-hawaiian-crush-extrait-de-parfum-50ml", (50,)),
            "Imperium": ("https://officialmykonos.com/products/mykonos-imperium-extrait-de-parfum-100ml", (100,)),
            "Inception": ("https://officialmykonos.com/products/mykonos-inception-extrait-de-parfum-50ml", (50, 100)),
            "Inferno": ("https://officialmykonos.com/products/mykonos-inferno-extrait-de-parfum-100ml", (50, 100)),
            "Luminos": ("https://officialmykonos.com/products/mykonos-luminos-extrait-de-parfum-50ml", (50,)),
            "Marbella": ("https://officialmykonos.com/products/mykonos-marbella-extrait-de-parfum-100ml", (50, 100)),
            "Matcha Latte": ("https://officialmykonos.com/products/mykonos-matcha-latte-extrait-de-parfum-50ml", (50,)),
            "Mayfair": ("https://officialmykonos.com/products/mykonos-mayfair-extrait-de-parfum-100ml", (50, 100)),
            "Milk Drops": ("https://officialmykonos.com/products/mykonos-milk-drops-extrait-de-parfum-50ml", (50,)),
            "Monaco Royale": ("https://officialmykonos.com/products/mykonos-monaco-royale-extrait-de-parfum-50ml-100ml", (50, 100)),
            "Moroccan Vanilla": ("https://officialmykonos.com/products/mykonos-moroccan-vanilla-extrait-de-parfum-100ml", (100,)),
            "Musk Aura": ("https://officialmykonos.com/products/mykonos-musk-aura-extrait-de-parfum-100ml", (100,)),
            "Nautilus": ("https://officialmykonos.com/products/mykonos-nautilus-extrait-de-parfum-100ml", (100,)),
            "On The Rocks": ("https://officialmykonos.com/products/mykonos-on-the-rocks-extrait-de-parfum-100ml", (100,)),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, sizes) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("concentration"), "Extrait de Parfum")
                matching_products = [
                    product for product in CATALOG.get("products", [])
                    if product.get("brand_name") == "Mykonos"
                    and product.get("canonical_name") == name
                ]
                self.assertEqual(len(matching_products), 1)
                for size in sizes:
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row["product_id"]
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("concentration"), "Extrait de Parfum")
                    self.assertEqual(matches[0].get("source_evidence_url"), source_url)


    def test_mykonos_remaining_current_collection_products_have_individual_official_page_provenance(self):
        expected = {
            "Paradise": ("https://officialmykonos.com/products/mykonos-paradise-extrait-de-parfum-50ml", {"50": "Extrait de Parfum"}),
            "Penthouse": ("https://officialmykonos.com/products/mykonos-penthouse-extrait-de-parfum-100ml", {"50": "Extrait de Parfum", "100": "Extrait de Parfum"}),
            "Pink Beach": ("https://officialmykonos.com/products/mykonos-pink-beach-edp-50ml", {"50": "Eau de Parfum"}),
            "Pink Drops": ("https://officialmykonos.com/products/mykonos-pink-drops-extrait-de-parfum-50ml", {"50": "Extrait de Parfum"}),
            "Reflection Elixir": ("https://officialmykonos.com/products/mykonos-reflection-elixir-extrait-de-parfum-50ml", {"50": "Extrait de Parfum"}),
            "Reflection": ("https://officialmykonos.com/products/mykonos-reflection-extrait-de-parfum-50ml-100ml", {"50": "Extrait de Parfum", "100": "Extrait de Parfum"}),
            "Royal Ispahan": ("https://officialmykonos.com/products/mykonos-royal-ispahan-extrait-de-parfum-50ml-100ml", {"50": "Extrait de Parfum", "100": "Extrait de Parfum"}),
            "Satin Blanc": ("https://officialmykonos.com/products/mykonos-satin-blanc-extrait-de-parfum-100ml", {"100": "Extrait de Parfum"}),
            "Senja": ("https://officialmykonos.com/products/mykonos-senja-edp-50ml", {"50": "Extrait de Parfum"}),
            "Silent Whisper": ("https://officialmykonos.com/products/mykonos-silent-whisper-extrait-de-parfum-50ml-100ml", {"50": "Extrait de Parfum", "100": "Extrait de Parfum"}),
            "Slow Living": ("https://officialmykonos.com/products/mykonos-slow-living-edp-50ml", {"50": "Eau de Parfum", "100": "Extrait de Parfum"}),
            "Sorrento": ("https://officialmykonos.com/products/mykonos-sorrento-extrait-de-parfum-50ml-100ml", {"50": "Extrait de Parfum", "100": "Extrait de Parfum"}),
            "Sparkling Rosé": ("https://officialmykonos.com/products/mykonos-sparkling-rose-extrait-de-parfum-100ml", {"100": "Extrait de Parfum"}),
            "Stilettos": ("https://officialmykonos.com/products/mykonos-stilettos-edp-50ml", {"50": "Eau de Parfum"}),
            "Untamed": ("https://officialmykonos.com/products/mykonos-untamed-extrait-de-parfum-100ml", {"100": "Extrait de Parfum"}),
            "Utopia": ("https://officialmykonos.com/products/mykonos-utopia-extrait-de-parfum-100ml", {"100": "Extrait de Parfum"}),
            "Vanilla Clouds": ("https://officialmykonos.com/products/mykonos-vanilla-clouds-extrait-de-parfum-50ml-1", {"50": "Extrait de Parfum"}),
            "Verve": ("https://officialmykonos.com/products/mykonos-verve-extrait-de-parfum-when-in-paris-edp-50ml", {"50": "Extrait de Parfum"}),
            "Xoxo Rosy": ("https://officialmykonos.com/products/mykonos-xoxo-rosy-edp-50ml", {"50": "Eau de Parfum"}),
            "MyEgo": ("https://officialmykonos.com/products/mykonos-x-alterego-myego-extrait-de-parfum-50ml-100ml", {"50": "Extrait de Parfum", "100": "Extrait de Parfum"}),
            "Empire x RRQ": ("https://officialmykonos.com/products/mykonos-x-rrq-empire-extrait-de-parfum-50ml-100ml", {"50": "Extrait de Parfum", "100": "Extrait de Parfum"}),
            "Glitch": ("https://officialmykonos.com/products/mykonos-x-setiawanade-glitch-extrait-de-parfum-50ml", {"50": "Extrait de Parfum", "100": "Extrait de Parfum"}),
            "Invade": ("https://officialmykonos.com/products/mykonos-x-setiawanade-invade-extrait-de-parfum-50ml", {"50": "Extrait de Parfum"}),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Mykonos"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, sizes) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                matching_products = [
                    product for product in CATALOG.get("products", [])
                    if product.get("brand_name") == "Mykonos"
                    and product.get("canonical_name") == name
                ]
                self.assertEqual(len(matching_products), 1)
                if name == "Slow Living":
                    self.assertNotIn("concentration", row)
                else:
                    self.assertTrue(row.get("concentration"))
                for size, concentration in sizes.items():
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row["product_id"]
                        and variant.get("size_ml") == int(size)
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("concentration"), concentration)
                    self.assertEqual(matches[0].get("source_evidence_url"), source_url)


    def test_aromatix_official_french_avenue_detail_pages_and_100ml_variants(self):
        expected = {
            "Carnal Desire": ("https://frenchavenue.com/products/carnal-desire", "Eau de Parfum"),
            "Forbidden Fruit": ("https://frenchavenue.com/products/aromatix-forbidden-fruit", "Eau de Parfum"),
            "Frostbite": ("https://frenchavenue.com/products/aromatix-frostbite", "Extrait de Parfum"),
            "Magnetiq": ("https://frenchavenue.com/products/aromatix-magnetiq", "Eau de Parfum"),
            "Naughty Dates": ("https://frenchavenue.com/products/aromatix-naughty-dates", "Eau de Parfum"),
            "Royal Taboo": ("https://frenchavenue.com/products/royal-taboo", "Extrait de Parfum"),
            "Sun Kissed": ("https://frenchavenue.com/products/aromatix-sunkissed", "Eau de Parfum"),
            "Teas Me": ("https://frenchavenue.com/products/aromatix-teas-me", "Eau de Parfum"),
            "X Xandal": ("https://frenchavenue.com/products/aromatix-x-xandal", "Extrait de Parfum"),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Aromatix"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, concentration) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("concentration"), concentration)
                self.assertEqual(row.get("formats_ml"), [100])
                matches = [
                    variant for variant in variants
                    if variant.get("product_id") == row["product_id"]
                    and variant.get("size_ml") == 100
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("concentration"), concentration)
                self.assertEqual(matches[0].get("source_evidence_url"), source_url)

    def test_aromatix_plantine_blanc_official_identity_without_unsupported_variant(self):
        rows = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Aromatix"
            and row.get("canonical_name") == "Plantine Blanc"
        ]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), "https://frenchavenue.com/products/aromatix-plantine-blanc")
        self.assertIn("Platine Blanc", row.get("aliases", []))
        self.assertNotIn("concentration", row)
        self.assertNotIn("formats_ml", row)
        self.assertFalse(any(v.get("product_id") == row["product_id"] for v in CATALOG.get("variants", [])))

    def test_aromatix_ora_and_roza_remain_listing_level_until_official_detail_pages_are_found(self):
        for name in ("Ora", "Roza"):
            with self.subTest(name=name):
                rows = [
                    row for row in CATALOG.get("products", [])
                    if row.get("brand_name") == "Aromatix"
                    and row.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.get("identity_status"), "source_listed_name")
                self.assertEqual(row.get("source_url"), "https://www.notino.be/french-avenue/aromatix/")
                self.assertNotIn("concentration", row)
                self.assertNotIn("formats_ml", row)
                self.assertFalse(any(v.get("product_id") == row["product_id"] for v in CATALOG.get("variants", [])))


    def test_maison_asrar_second_collection_page_has_individual_official_detail_provenance(self):
        expected = {
            "Dubai Milano": "https://maisonasrar.com/products/dubai-milano",
            "Dubai London": "https://maisonasrar.com/products/dubai-london",
            "Dubai Miami": "https://maisonasrar.com/products/dubai-miami",
            "III Thriller": "https://maisonasrar.com/products/iii-thriller",
            "Milky Way": "https://maisonasrar.com/products/milky-way",
            "Vanguard": "https://maisonasrar.com/products/vanguard",
            "Muharib": "https://maisonasrar.com/products/muharib",
            "Faris Al Arab": "https://maisonasrar.com/products/faris-al-arab",
            "Vanilla Seduction": "https://maisonasrar.com/products/vanilla-seduction",
            "Vanilla Aura": "https://maisonasrar.com/products/vanilla-aura",
            "Throne Eclipse": "https://maisonasrar.com/products/throne-eclipse",
            "Throne": "https://maisonasrar.com/products/throne",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        variants = CATALOG.get("variants", [])
        for name, source_url in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                matching = [
                    variant for variant in variants
                    if variant.get("product_id") == row["product_id"]
                ]
                if name == "Vanilla Aura":
                    # Its 100 ml EDP variant remains supported by the
                    # individual retailer page; the Maison Asrar page itself
                    # is used only to verify the canonical identity.
                    self.assertEqual(len(matching), 1)
                    self.assertEqual(matching[0].get("size_ml"), 100)
                    self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                    self.assertEqual(
                        matching[0].get("source_evidence_url"),
                        "https://shop-gulforchid.com/products/vanilla-aura",
                    )
                else:
                    self.assertEqual(matching, [])
                    self.assertNotIn("formats_ml", row)
                    self.assertNotIn("concentration", row)


    def test_maison_asrar_third_new_arrivals_page_has_individual_official_detail_provenance(self):
        expected = {
            "Khayyal": "https://maisonasrar.com/products/khayyal",
            "Mohra": "https://maisonasrar.com/products/mohrab",
            "Hikaya": "https://maisonasrar.com/products/hikaya",
            "Hilm": "https://maisonasrar.com/products/hilm",
            "Cascade": "https://maisonasrar.com/products/cascade",
            "Tornado": "https://maisonasrar.com/products/tornado",
            "Wadi": "https://maisonasrar.com/products/wadi",
            "DXB": "https://maisonasrar.com/products/dxb",
            "Legacy": "https://maisonasrar.com/products/legacy",
            "Vanilla Voyage": "https://maisonasrar.com/products/vanilla-voyage-eau-de-parfum",
            "Vision": "https://maisonasrar.com/products/vision",
            "Oh Honey!": "https://maisonasrar.com/products/oh-honey-eau-de-parfum",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        variants = CATALOG.get("variants", [])
        for name, source_url in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertNotIn("formats_ml", row)
                self.assertNotIn("concentration", row)
                self.assertFalse(any(
                    variant.get("product_id") == row["product_id"]
                    for variant in variants
                ))


    def test_maison_asrar_fourth_and_fifth_new_arrivals_pages_brand_owned_products(self):
        expected = {
            "Date Night": "https://maisonasrar.com/products/date-night",
            "Larimar": "https://maisonasrar.com/products/larimar",
            "Rubellite": "https://maisonasrar.com/products/rubellite",
            "Nada": "https://maisonasrar.com/products/nada",
            "Omniya": "https://maisonasrar.com/products/omniya",
            "Coffee Blend": "https://maisonasrar.com/products/coffee-blend-eau-de-parfum",
            "Lumiere": "https://maisonasrar.com/products/lumiere",
            "Soirée": "https://maisonasrar.com/products/soiree",
            "Rey": "https://maisonasrar.com/products/rey-eau-de-parfum-100ml-maison-asrar",
            "Leo": "https://maisonasrar.com/products/maison-asrar-leo-eau-de-parfum-100ml",
            "Hunter": "https://maisonasrar.com/products/maison-asrar-hunter-eau-de-parfum-100ml",
            "Bloom Bloom": "https://maisonasrar.com/products/bloom-bloom-eau-de-parfum-100ml",
            "Lolita": "https://maisonasrar.com/products/lolita-eau-de-parfum-100ml",
            "Bonita": "https://maisonasrar.com/products/bonita-eau-de-parfum-100ml",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Asrar"
        }
        variants = CATALOG.get("variants", [])
        for name, source_url in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertNotIn("formats_ml", row)
                self.assertNotIn("concentration", row)
                self.assertFalse(any(
                    variant.get("product_id") == row["product_id"]
                    for variant in variants
                ))

if __name__ == "__main__":
    unittest.main()
