"""Regression guard for the user-requested fragrance brand coverage."""
import json
import re
import unicodedata
import unittest
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))


def normalize_catalog_name(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

# Lower bounds from the reconciled 2026-11-08 catalog snapshot. These are
# canonical fragrance identities, not SKU/variant counts or claims of
# worldwide historical completeness.
MINIMUM_BRAND_COUNTS = {
    "Velixir": 28,
    "Maison Asrar": 120,
    "Swiss Arabian": 41,
    "Paris Corner": 246,
    "Khadlaj": 116,
    "Bujairami": 142,
    "Assaf": 140,
    "Al Wataniah": 86,
    "French Avenue": 119,
    "Arabiyat Prestige": 118,
    "Gulf Orchid": 32,
    "Afnan": 87,
    "Lattafa": 115,
    "Aromatix": 12,
    "Zimaya": 76,
    "Al Haramain": 107,
    "Games of Spades": 32,
    "Maison Alhambra": 207,
    "Mykonos": 72,
    "Armaf": 191,
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


    def test_catalog_product_and_variant_ids_are_unique(self):
        product_ids = [row.get("product_id") for row in CATALOG.get("products", [])]
        variant_ids = [row.get("variant_id") for row in CATALOG.get("variants", [])]
        self.assertTrue(all(product_ids))
        self.assertTrue(all(variant_ids))
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

    def test_every_variant_references_a_real_product_and_positive_size(self):
        product_ids = {row.get("product_id") for row in CATALOG.get("products", [])}
        for index, row in enumerate(CATALOG.get("variants", [])):
            with self.subTest(variant=index):
                self.assertIn(row.get("product_id"), product_ids)
                self.assertIsInstance(row.get("size_ml"), (int, float))
                self.assertGreater(row.get("size_ml"), 0)

    def test_every_catalog_identity_maps_to_a_registered_family_product(self):
        registry_path = BACKEND / "family_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registered = {
            (
                str(family.get("brand") or "").strip(),
                normalize_catalog_name(product.get("canonical_name")),
            )
            for family in registry.get("families", [])
            for product in family.get("products", [])
        }
        family_ids = {
            family.get("family_id") for family in registry.get("families", [])
        }
        for index, row in enumerate(CATALOG.get("products", [])):
            key = (
                str(row.get("brand_name") or row.get("brand") or "").strip(),
                normalize_catalog_name(row.get("canonical_name") or row.get("name")),
            )
            with self.subTest(product=index):
                self.assertIn(row.get("family_id"), family_ids)
                self.assertIn(key, registered)


    def test_maison_alhambra_avant_official_page_and_100ml_variant(self):
        self._assert_maison_alhambra_verified_variant(
            "Avant",
            "https://maisonalhambra-usa.com/products/maison-alhambra-avant-eau-de-parfum-for-everyone",
            "6291107459110",
        )

    def test_maison_alhambra_camille_official_page_and_100ml_variant(self):
        self._assert_maison_alhambra_verified_variant(
            "Camille",
            "https://maisonalhambra-usa.com/products/maison-alhambra-camille-eau-de-parfum-for-women",
            "6290360599236",
        )

    def _assert_maison_alhambra_verified_variant(self, name, source_url, gtin):
        rows = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Alhambra"
            and row.get("canonical_name") == name
        ]
        self.assertEqual(len(rows), 1)
        product = rows[0]
        self.assertEqual(product.get("identity_status"), "source_verified_name")
        self.assertEqual(product.get("source_url"), source_url)
        self.assertEqual(product.get("concentration"), "Eau de Parfum")
        self.assertIn(100, product.get("formats_ml", []))
        matches = [
            row for row in CATALOG.get("variants", [])
            if row.get("product_id") == product["product_id"]
            and row.get("size_ml") == 100
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].get("concentration"), "Eau de Parfum")
        self.assertEqual(matches[0].get("gtin"), gtin)
        self.assertEqual(matches[0].get("source_evidence_url"), source_url)


if __name__ == "__main__":
    unittest.main()
