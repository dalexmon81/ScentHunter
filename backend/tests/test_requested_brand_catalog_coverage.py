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
    "Paris Corner": 253,
    "Khadlaj": 116,
    "Bujairami": 142,
    "Assaf": 140,
    "Al Wataniah": 86,
    "French Avenue": 119,
    "Arabiyat Prestige": 118,
    "Gulf Orchid": 32,
    "Afnan": 87,
    "Lattafa": 119,
    "Aromatix": 12,
    "Zimaya": 76,
    "Al Haramain": 107,
    "Games of Spades": 32,
    "Maison Alhambra": 214,
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


    def test_paris_corner_confidential_100ml_official_product_page(self):
        source = "https://www.pariscornerperfumes.com/products/confidential-100ml"
        rows = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
            and row.get("canonical_name") == "Confidential 100ML"
        ]
        self.assertEqual(len(rows), 1)
        product = rows[0]
        self.assertEqual(product.get("identity_status"), "source_verified_name")
        self.assertEqual(product.get("source_url"), source)
        self.assertIn(100, product.get("formats_ml", []))
        matches = [
            row for row in CATALOG.get("variants", [])
            if row.get("product_id") == product["product_id"]
            and row.get("size_ml") == 100
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].get("source_evidence_url"), source)
        self.assertNotIn("concentration", product)
        self.assertNotIn("concentration", matches[0])


    def test_maison_alhambra_new_in_official_pages_and_gtin_variants_are_verified(self):
        expected = {
            "Jubilant Vitality": ("https://maisonalhambra-usa.com/products/maison-alhambra-jubilant-vitality-eau-de-parfum-for-everyone", 100, "6290362343530"),
            "In Perfect Harmony": ("https://maisonalhambra-usa.com/products/maison-alhambra-in-perfect-harmony-eau-de-parfum-for-everyone", 60, "6290362340676"),
            "Sceptre Desert": ("https://maisonalhambra-usa.com/products/maison-alhambra-sceptre-desert-eau-de-parfum-for-everyone", 100, "6290362340621"),
            "Eclat De Lune": ("https://maisonalhambra-usa.com/products/maison-alhambra-eclat-de-lune-eau-de-parfum-for-women", 100, "6290360599212"),
            "Lava": ("https://maisonalhambra-usa.com/products/maison-alhambra-lava-eau-de-parfum-for-everyone", 100, "6290360599267"),
            "La Charmante": ("https://maisonalhambra-usa.com/products/maison-alhambra-la-charmante-eau-de-parfum-for-everyone", 100, "6290362340164"),
            "La Charmante Eclatant": ("https://maisonalhambra-usa.com/products/maison-alhambra-la-charmante-eclatant-eau-de-parfum-for-everyone", 100, "6290362340171"),
            "Your Touch Santal": ("https://maisonalhambra-usa.com/products/maison-alhambra-your-touch-santal-eau-de-parfum-for-everyone", 100, "6290362347989"),
            "Victoria Flower Rosa Lilium": ("https://maisonalhambra-usa.com/products/maison-alhambra-victoria-flower-rosa-lilium-eau-de-parfum-for-women", 100, "6290362340966"),
            "Victorioso Heroic": ("https://maisonalhambra-usa.com/products/maison-alhambra-victorioso-heroic-eau-de-parfum-for-men", 100, "6290362340584"),
            "Rose Origami": ("https://maisonalhambra-usa.com/products/maison-alhambra-rose-origami-eau-de-parfum-for-everyone", 100, "6290362340928"),
            "Opera Rouge": ("https://maisonalhambra-usa.com/products/maison-alhambra-opera-rouge-eau-de-parfum-for-everyone", 100, "6290362340881"),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Maison Alhambra"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size, gtin) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                self.assertEqual(row.get("concentration"), "Eau de Parfum")
                self.assertIn(gtin, row.get("gtins", []))
                matches = [
                    variant for variant in variants
                    if variant.get("product_id") == row.get("product_id")
                    and variant.get("size_ml") == size
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("gtin"), gtin)
                self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_paris_corner_official_storefront_batch_a_detail_pages_and_sizes(self):
        expected = {
            "Arcana": ("https://www.pariscornerperfumes.com/products/arcana", None),
            "Arwa": ("https://www.pariscornerperfumes.com/products/arwa", None),
            "Atomise Intensive Men": ("https://www.pariscornerperfumes.com/products/atomise-intensive-men", None),
            "Azm": ("https://www.pariscornerperfumes.com/products/azm", 100),
            "Banana Bliss": ("https://www.pariscornerperfumes.com/products/banana-bliss-100ml", 100),
            "Bayn Al Asrar": ("https://www.pariscornerperfumes.com/products/bayn-al-asrar", None),
            "Blackberry Wish": ("https://www.pariscornerperfumes.com/products/blackberry-wish", 100),
            "Cake Temptation": ("https://www.pariscornerperfumes.com/products/cake-temptation-100ml", 100),
            "Camaro Homme Intense": ("https://www.pariscornerperfumes.com/products/camaro-homme-intense", None),
            "Camp Fire Emir Factory Edition": ("https://www.pariscornerperfumes.com/products/camp-fire-emir-factory-edition", 100),
            "Caramel Bash": ("https://www.pariscornerperfumes.com/products/caramel-bash-1", 100),
            "Cedrat Essence Emir": ("https://www.pariscornerperfumes.com/products/cedart-essence-emir", 75),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_paris_corner_official_storefront_batch_b_detail_pages_and_sizes(self):
        expected = {
            "Cosmopolitan Newyork": ("https://www.pariscornerperfumes.com/products/cosmopolitan-newyork", None),
            "Creamy Biscuit": ("https://www.pariscornerperfumes.com/products/creamy-biscuit-100ml", 100),
            "Dar Al Oud": ("https://www.pariscornerperfumes.com/products/dar-al-oud", 100),
            "Date Caramel": ("https://www.pariscornerperfumes.com/products/date-caramel", 100),
            "December Ambar": ("https://www.pariscornerperfumes.com/products/december-ambar", 85),
            "December Rose": ("https://www.pariscornerperfumes.com/products/dcember-rose", None),
            "December Vanilla": ("https://www.pariscornerperfumes.com/products/december-vanilla", None),
            "Doris Pink": ("https://www.pariscornerperfumes.com/products/doris-pink", 100),
            "Dulzura": ("https://www.pariscornerperfumes.com/products/dulzura", 100),
            "Dusky Vanilla": ("https://www.pariscornerperfumes.com/products/dusky-vanilla", 100),
            "Ecstatic Blanc Fleur": ("https://www.pariscornerperfumes.com/products/ecstatic-blanc-fleur", 100),
            "Elania Emir": ("https://www.pariscornerperfumes.com/products/elania-emir", 100),
            "English Leather": ("https://www.pariscornerperfumes.com/products/english-leather", 100),
            "Enormity": ("https://www.pariscornerperfumes.com/products/enormity", 100),
            "Eshal Musk": ("https://www.pariscornerperfumes.com/products/eshal-musk", 100),
            "Eshal Vanilla": ("https://www.pariscornerperfumes.com/products/eshal-vanilla", 100),
            "Eternal Coffee": ("https://www.pariscornerperfumes.com/products/eternal-coffee", None),
            "Eternal Meadows": ("https://www.pariscornerperfumes.com/products/eternal-meadows", None),
            "Eternal Musk": ("https://www.pariscornerperfumes.com/products/eternal-musk", None),
            "Farah": ("https://www.pariscornerperfumes.com/products/farah", 100),
            "Fascination Emir": ("https://www.pariscornerperfumes.com/products/fascination", None),
            "Fayora": ("https://www.pariscornerperfumes.com/products/fayora", 100),
            "Fayora Oshino": ("https://www.pariscornerperfumes.com/products/fayora-oshino", 100),
            "Fig Fete": ("https://www.pariscornerperfumes.com/products/fig-fete", 100),
            "Fire Your Desire Emir": ("https://www.pariscornerperfumes.com/products/fire-your-desire-emir", 100),
            "Forbidden Sugar Emir": ("https://www.pariscornerperfumes.com/products/forbidden-sugar-emir", 100),
            "Frenetic Delicieuse": ("https://www.pariscornerperfumes.com/products/frenetic-delicieuse", 80),
            "Frenetic Homme Intense": ("https://www.pariscornerperfumes.com/products/frenetichomme-intense", 80),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_paris_corner_official_storefront_batch_b_detail_pages_and_explicit_sizes(self):
        expected = {
            "Celestial Emir": ("https://www.pariscornerperfumes.com/products/celestial", 100),
            "Charuto Regal Reserve": ("https://www.pariscornerperfumes.com/products/charuto-regal-reserve", None),
            "Charuto Tobacco Vanille": ("https://www.pariscornerperfumes.com/products/charuto-tobacco-vanille", 100),
            "Cherry Cola": ("https://www.pariscornerperfumes.com/products/cherry-cola", None),
            "Cherry Gossip": ("https://www.pariscornerperfumes.com/products/cherry-gossip", 100),
            "Choco Cult": ("https://www.pariscornerperfumes.com/products/choco-cult", 100),
            "Choco Lait": ("https://www.pariscornerperfumes.com/products/choco-lait", 100),
            "Coconut Lagoon": ("https://www.pariscornerperfumes.com/products/coconut-lagoon-100ml", None),
            "Confidential": ("https://www.pariscornerperfumes.com/products/confidential-100ml", 100),
            "Cornflower Delight": ("https://www.pariscornerperfumes.com/products/cornflower-delight", 100),
            "Cosmic Giardino": ("https://www.pariscornerperfumes.com/products/cosmic-giardino", 100),
            "Cosmopolitan Dubai": ("https://www.pariscornerperfumes.com/products/cosmopolitan-dubai", None),
            "Cosmopolitan London": ("https://www.pariscornerperfumes.com/products/cosmopolitan-london", None),
        }
        products = {
            str(row.get("canonical_name") or row.get("name") or "").strip(): row
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_url"), source)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_paris_corner_official_storefront_batch_c_detail_pages_and_sizes(self):
        expected = {
            "Frenetic Men": ("https://www.pariscornerperfumes.com/products/frenetic-men", 100),
            "Frenetic Red Tempt": ("https://www.pariscornerperfumes.com/products/frenetic-red-tempt", 80),
            "Frenetic Tobacco Honey": ("https://www.pariscornerperfumes.com/products/frenetic-tobacco-honey", 100),
            "Harrier Absolute": ("https://www.pariscornerperfumes.com/products/harrier-absoulte", 100),
            "Hidden Halo": ("https://www.pariscornerperfumes.com/products/hidden-halo", 100),
            "Honeyed Fantasy": ("https://www.pariscornerperfumes.com/products/honeyed-fantasy", 100),
            "Hurriya": ("https://www.pariscornerperfumes.com/products/hurriya", 100),
            "Ibisco Nirvana": ("https://www.pariscornerperfumes.com/products/ibisco-nirvana", None),
            "Identity Oud Crescent": ("https://www.pariscornerperfumes.com/products/identity-oud-crescent", 100),
            "Identity Rose & Leather": ("https://www.pariscornerperfumes.com/products/identity-rose-leather", 100),
            "Identity Unique Portrait": ("https://www.pariscornerperfumes.com/products/identity-unique-portrait", 100),
            "Indomitable": ("https://www.pariscornerperfumes.com/products/indomitable", 100),
            "Intense Oud": ("https://www.pariscornerperfumes.com/products/intense-oud-arabian", 100),
            "Intense Oud Saffron": ("https://www.pariscornerperfumes.com/products/intense-oud-saffron", 100),
            "Intense Wayfarer": ("https://www.pariscornerperfumes.com/products/intense-wayfarer", None),
            "Intima Red": ("https://www.pariscornerperfumes.com/products/intima-red", 100),
            "Jardin des Papillons": ("https://www.pariscornerperfumes.com/products/jardin-des-papillons", 100),
            "Juicy Melange": ("https://www.pariscornerperfumes.com/products/juicy-melange", None),
            "Just Bergamot Emir Factory Edition": ("https://www.pariscornerperfumes.com/products/just-bergamot-emir-factory-edition", 100),
            "Kaheela Platinum": ("https://www.pariscornerperfumes.com/products/kaheela-platinum", None),
            "Khair": ("https://www.pariscornerperfumes.com/products/khair", None),
            "Khair Confection": ("https://www.pariscornerperfumes.com/products/khair-confection", None),
            "Khair Felicity": ("https://www.pariscornerperfumes.com/products/khair-felicity-100ml", None),
            "Khair Fusion": ("https://www.pariscornerperfumes.com/products/khair-fusion", None),
            "Khair Peach Delulu": ("https://www.pariscornerperfumes.com/products/khair-peach-delulu", 100),
            "Khair Pistachio": ("https://www.pariscornerperfumes.com/products/khair-pistachio", None),
            "Khayal": ("https://www.pariscornerperfumes.com/products/khayal-100ml", 100),
            "La Nuit Pendora": ("https://www.pariscornerperfumes.com/products/la-nuit-pendora", 100),
            "La Serpiente Emir": ("https://www.pariscornerperfumes.com/products/la-serpiente-emir", 100),
            "Le Charme": ("https://www.pariscornerperfumes.com/products/la-charme-emir", 100),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_paris_corner_magic_oud_series_official_detail_pages_and_100ml_variants(self):
        expected = {
            "Magic Oud Dark Roses": "https://www.pariscornerperfumes.com/products/magic-oud-dark-roses",
            "Magic Oud In Pure Zaffron": "https://www.pariscornerperfumes.com/products/magic-oud-in-pure-zaffron",
            "Magic Oud Kalimath": "https://www.pariscornerperfumes.com/products/magic-oud-kalimath",
            "Magic Oud Kashmir Musk": "https://www.pariscornerperfumes.com/products/magic-oud-kashmir-musk",
            "Magic Oud Sandal Wood": "https://www.pariscornerperfumes.com/products/magic-oud-sandal-wood",
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, source in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                self.assertIn(100, row.get("formats_ml", []))
                matches = [
                    variant for variant in variants
                    if variant.get("product_id") == row.get("product_id")
                    and variant.get("size_ml") == 100
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("source_url"), source)
                self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_paris_corner_official_storefront_batch_d_detail_pages_and_sizes(self):
        expected = {
            "Lueur d'Espoir Arena Intense": ("https://www.pariscornerperfumes.com/products/lueur-d-espoir-arena-intense", 100),
            "Lueur d'Espoir Memories of Summer": ("https://www.pariscornerperfumes.com/products/lueur-d-espoir-memories-of-summer", 100),
            "Lueur d'Espoir Serene Grove": ("https://www.pariscornerperfumes.com/products/lueur-d-espoir-serene-grove", 100),
            "Lueur d'Espoir Silhouette": ("https://www.pariscornerperfumes.com/products/lueur-d-espoir-silhouette", 100),
            "Lullaby": ("https://www.pariscornerperfumes.com/products/lullaby", 100),
            "Magic Oud Dark Roses": ("https://www.pariscornerperfumes.com/products/magic-oud-dark-roses",  100),
            "Magic Oud In Pure Zaffron": ("https://www.pariscornerperfumes.com/products/magic-oud-in-pure-zaffron",  100),
            "Magic Oud Kalimath": ("https://www.pariscornerperfumes.com/products/magic-oud-kalimath",  100),
            "Magic Oud Kashmir Musk": ("https://www.pariscornerperfumes.com/products/magic-oud-kashmir-musk",  100),
            "Magic Oud Sandal Wood": ("https://www.pariscornerperfumes.com/products/magic-oud-sandal-wood",  100),
            "Manaal": ("https://www.pariscornerperfumes.com/products/manaal-1", None),
            "Mango Flames": ("https://www.pariscornerperfumes.com/products/mango-flames", 100),
            "Mango Jugoso": ("https://www.pariscornerperfumes.com/products/mango-jugoso-100ml", 100),
            "Mango Punch": ("https://www.pariscornerperfumes.com/products/mango-punch", None),
            "Mawj Appletini": ("https://www.pariscornerperfumes.com/products/mawj-appletini", None),
            "Mawj Cognac Blaze": ("https://www.pariscornerperfumes.com/products/mawj-cognac-blaze", None),
            "Mawj Moscow Mule": ("https://www.pariscornerperfumes.com/products/mawj-moscow-mule", None),
            "Mehwish": ("https://www.pariscornerperfumes.com/products/mehwish", 80),
            "Metalico Emir": ("https://www.pariscornerperfumes.com/products/metalico-emir", 100),
            "Miel Obscura": ("https://www.pariscornerperfumes.com/products/miel-obscura", 100),
            "Miel Vanille": ("https://www.pariscornerperfumes.com/products/miel-vanille", None),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_paris_corner_official_storefront_batch_e_detail_pages_and_sizes(self):
        expected = {
            "Ministry of Oud Greatest": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-greatest", 100),
            "Ministry of Oud Gladiators Oath": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-gladiators-oath", 100),
            "Ministry of Oud Maestro's Symphony": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-maestro-s-symphony", 100),
            "Ministry of Oud Nile Whispers": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-nile-whispers", 100),
            "Ministry of Oud Oud Beyond the Wall": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-beyond-the-wall", 100),
            "Ministry of Oud Romance Reverie": ("https://www.pariscornerperfumes.com/products/ministry-of-oud-romance-reverie", 100),
            "Minya": ("https://www.pariscornerperfumes.com/products/minya-100ml", 100),
            "Minya Coco Lush": ("https://www.pariscornerperfumes.com/products/minya-coco-lush", None),
            "Misty Dawn Musk Collection": ("https://www.pariscornerperfumes.com/products/misty-dawn-musk-collection-1", None),
            "Mysterium": ("https://www.pariscornerperfumes.com/products/mysterium", 100),
            "Nada Blumingle": ("https://www.pariscornerperfumes.com/products/nada-blumingle", 100),
            "Nada Whimsical": ("https://www.pariscornerperfumes.com/products/nada-whimsical", 100),
            "Nada Wink": ("https://www.pariscornerperfumes.com/products/nada-wink", 100),
            "Nectarine Haze": ("https://www.pariscornerperfumes.com/products/nectarine-haze", 100),
            "Neon Star": ("https://www.pariscornerperfumes.com/products/neon-star", 100),
            "Noir d'Arabie": ("https://www.pariscornerperfumes.com/products/noir-darabie", None),
            "Nouf": ("https://www.pariscornerperfumes.com/products/nouf", None),
            "Ophidian Black Cherry": ("https://www.pariscornerperfumes.com/products/ophidian-black-cherry-100ml", 100),
            "Ophidian Mango Bliss": ("https://www.pariscornerperfumes.com/products/ophidian-mango-bliss", None),
            "Ophidian Sweet Surrender": ("https://www.pariscornerperfumes.com/products/ophidian-sweet-surrender", None),
            "Opulentia Empyreal Emir": ("https://www.pariscornerperfumes.com/products/opulentia-empyreal-emir", 100),
            "Opulentia Flame Emir": ("https://www.pariscornerperfumes.com/products/opulentia-flame-emir", 100),
            "Opulentia Inverno Emir": ("https://www.pariscornerperfumes.com/products/opulentia-inverno-emir", 100),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_url"), source)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_lattafa_official_detail_pages_and_explicit_sizes_are_verified(self):
        expected = {
            "Fahad": ("https://lattafa.com/product/lattafa-fahad-80-ml/", 80),
            "Khamrah Waha": ("https://lattafa.com/product/khamrah-waha/", 100),
            "Sheikh Al Shuyukh Supreme": ("https://lattafa.com/product/sheikh-al-shuyukh-supreme/", 100),
            "Jouri": ("https://lattafa.com/product/jouri/", None),
            "Ana Abiyedh Passion": ("https://lattafa.com/product/ana-abiyedh-passion/", 60),
            "Ameerat Al Arab Sugar Crown": ("https://lattafa.com/product/ameerat-al-arab-sugar-crown/", 100),
            "Mishlah": ("https://lattafa.com/product/lattafa-mishlah/", 100),
            "Angham Second Song": ("https://lattafa.com/product/angham-second-song/", 100),
            "Maahir Honor": ("https://lattafa.com/product/maahir-honor/", 100),
            "Dalal": ("https://lattafa.com/product/dalal/", None),
            "Yara Elixir": ("https://lattafa.com/product/yara-elixir/", 100),
            "Asad Elixir": ("https://lattafa.com/product/asad-elixir/", 100),
        }
        products = {
            str(row.get("canonical_name") or row.get("name") or "").strip(): row
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "Lattafa"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_url"), source)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_lattafa_official_detail_pages_batch_two_and_explicit_sizes(self):
        expected = {
            "Musamam Black Intense": ("https://lattafa.com/product/musamam-black-intense/", None),
            "Raed Absolu": ("https://lattafa.com/product/raed-absolu/", 100),
            "Raed Intensely": ("https://lattafa.com/product/raed-intensely/", 100),
            "Liam Blue Shine": ("https://lattafa.com/product/liam-blue-shine/", 100),
            "Berry On Top": ("https://lattafa.com/product/berry-on-top/", None),
            "Washwasha": ("https://lattafa.com/product/washwasha/", 100),
            "Musk Salama": ("https://lattafa.com/product/musk-salama/", 100),
            "Eclaire Pistache": ("https://lattafa.com/product/eclaire-pistache/", 100),
            "Eclaire Banoffi": ("https://lattafa.com/product/eclaire-banoffi/", 100),
            "Ana Abiyedh Scarlet": ("https://lattafa.com/product/ana-abiyedh-scarlet/", 60),
        }
        products = {
            str(row.get("canonical_name") or row.get("name") or "").strip(): row
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "Lattafa"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_url"), source)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_paris_corner_official_storefront_batch_f_detail_pages_and_sizes(self):
        expected = {
            "Opulentia Primus Emir": ("https://www.pariscornerperfumes.com/products/opulentia-primus-emir", 100),
            "Oud and Vanille Emir": ("https://www.pariscornerperfumes.com/products/oud-and-vanille-emir", 75),
            "Oud Faek": ("https://www.pariscornerperfumes.com/products/oud-faek", None),
            "Oud Holidays": ("https://www.pariscornerperfumes.com/products/oud-holidays-100ml", 100),
            "Oud Wahaaj": ("https://www.pariscornerperfumes.com/products/oud-wahaaj-1", None),
            "Papillon des Vents": ("https://www.pariscornerperfumes.com/products/papillon-des-vents", 100),
            "Pear Potion": ("https://www.pariscornerperfumes.com/products/pear-potion", None),
            "Perseviron": ("https://www.pariscornerperfumes.com/products/perseviron", 100),
            "Perseviron Fig Hug": ("https://www.pariscornerperfumes.com/products/perseviron-fig-hug", 100),
            "Pinkling": ("https://www.pariscornerperfumes.com/products/pinkling", 100),
            "Plum Liquor": ("https://www.pariscornerperfumes.com/products/plum-liquor", None),
            "Poppy Pulse": ("https://www.pariscornerperfumes.com/products/poppy-pulse", 100),
            "Pour Me Wild": ("https://www.pariscornerperfumes.com/products/pour-me-wild", 100),
            "Praise": ("https://www.pariscornerperfumes.com/products/praise", 100),
            "Precision": ("https://www.pariscornerperfumes.com/products/precision", 100),
            "Prodigy": ("https://www.pariscornerperfumes.com/products/prodigy-100ml", 100),
            "Prodigy Noir": ("https://www.pariscornerperfumes.com/products/prodigy-noir-100ml", 100),
            "Protocol Edition": ("https://www.pariscornerperfumes.com/products/protocol-edition", 100),
            "Qawafi": ("https://www.pariscornerperfumes.com/products/qawafi-100ml", 100),
            "Qissa": ("https://www.pariscornerperfumes.com/products/qissa", None),
            "Qissa Delicious": ("https://www.pariscornerperfumes.com/products/qissa-delicious", None),
            "Qissa Gala": ("https://www.pariscornerperfumes.com/products/qissa-gala", 100),
            "Qissa Pink": ("https://www.pariscornerperfumes.com/products/qissa-pink", None),
            "Reham Vanilla Mood": ("https://www.pariscornerperfumes.com/products/reham-vanilla-mood", 100),
            "Reham Wild Mineral": ("https://www.pariscornerperfumes.com/products/reham-wild-mineral", 100),
            "Resurrection": ("https://www.pariscornerperfumes.com/products/resurrection", 100),
            "Rich Santal Emir Factory Edition": ("https://www.pariscornerperfumes.com/products/rich-santal-emir-factory-edition", 100),
            "Rifaaqat": ("https://www.pariscornerperfumes.com/products/rifaaqat", None),
        }
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Paris Corner"
        }
        variants = CATALOG.get("variants", [])
        for name, (source, size) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                row = products[name]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source)
                if size is not None:
                    self.assertIn(size, row.get("formats_ml", []))
                    matches = [
                        variant for variant in variants
                        if variant.get("product_id") == row.get("product_id")
                        and variant.get("size_ml") == size
                    ]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].get("source_url"), source)
                    self.assertEqual(matches[0].get("source_evidence_url"), source)


    def test_maison_alhambra_new_official_pages_have_verified_100ml_or_60ml_variants(self):
        expected = {
            "Jubilant Vitality": (
                "https://maisonalhambra-usa.com/products/maison-alhambra-jubilant-vitality-eau-de-parfum-for-everyone",
                100, "6290362343530",
            ),
            "In Perfect Harmony": (
                "https://maisonalhambra-usa.com/products/maison-alhambra-in-perfect-harmony-eau-de-parfum-for-everyone",
                60, "6290362340676",
            ),
            "Sceptre Desert": (
                "https://maisonalhambra-usa.com/products/maison-alhambra-sceptre-desert-eau-de-parfum-for-everyone",
                100, "6290362340621",
            ),
            "Eclat De Lune": (
                "https://maisonalhambra-usa.com/products/maison-alhambra-eclat-de-lune-eau-de-parfum-for-women",
                100, "6290360599212",
            ),
            "Lava": (
                "https://maisonalhambra-usa.com/products/maison-alhambra-lava-eau-de-parfum-for-everyone",
                100, "6290360599267",
            ),
            "La Charmante": (
                "https://maisonalhambra-usa.com/products/maison-alhambra-la-charmante-eau-de-parfum-for-everyone",
                100, "6290362340164",
            ),
            "La Charmante Eclatant": (
                "https://maisonalhambra-usa.com/products/maison-alhambra-la-charmante-eclatant-eau-de-parfum-for-everyone",
                100, "6290362340171",
            ),
            "Victorioso Heroic": (
                "https://maisonalhambra-usa.com/products/maison-alhambra-victorioso-heroic-eau-de-parfum-for-men",
                100, "6290362340584",
            ),
        }
        products = {
            str(row.get("canonical_name") or row.get("name") or "").strip(): row
            for row in CATALOG.get("products", [])
            if str(row.get("brand_name") or row.get("brand") or "").strip() == "Maison Alhambra"
        }
        variants = CATALOG.get("variants", [])
        for name, (source_url, size_ml, gtin) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source_url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                matching = [
                    variant for variant in variants
                    if variant.get("product_id") == product["product_id"]
                    and variant.get("size_ml") == size_ml
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("gtin"), gtin)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                self.assertIn("/products/", matching[0].get("source_evidence_url", ""))


if __name__ == "__main__":
    unittest.main()
