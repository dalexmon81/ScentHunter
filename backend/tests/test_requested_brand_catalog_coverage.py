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
    "Maison Asrar": 120,
    "Khadlaj": 165,
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


    def test_khadlaj_fragrantica_147_names_are_represented(self):
        expected = ["Bleu Glace","Caffe Latte","Cashmere Sunshine Musk","Cashmere Warm Oud","Cloud Candy","Code Viola Nectar","D'Love","Desert Rose","Gaith","Icon","Ihthiraam","Johayna Green","Kayaan Gold","Magnate Noble","Mansion","Maya","Mocha Latte","Muse","Musk Al Sabah","Musk Ice","Musk Pour Amber","Musk Pour Narcis","Ombre Notes","Opulence Bleu","Oud Noir","Pink Musk","Pure Musk","Purple Musk","Qarar","Rasayel Shagaf","Rasayel Vid","Ria","Rose & Romance","Rose Couture","Sara","Sawaar Vanille Blanc","Sensuous Night","Shiyaaka White","Strawberry Shake","Sueño","The Proposal Date Night","Titan","Uno Sensuale","Vanilla Kiss","Wow Oud","Zayaan Gold","Zayaan Silver","Barwaaz Pure Navy","Barwaaz Solid Grey","Biscotti Caramel Pop","Biscotti Date Toffee","Biscotti Melon Misk","Empire Crown","Empire Regent","Empire Victor","Fursan Brown","Fursan White","Ghadeer Gold","Ghadeer Silver","Hareem Al Sultan","Hareem Al Sultan Blue","Hareem Al Sultan Gold","Hareem Al Sultan Silver","Infini","Infini Absolute","Island","Island Dreams","Island Sun","Island Vanilla Dunes","Karus Amber Gold","Karus Blu Spice","Karus Gold Absolu","Karus Oud Fire","Karus Secret Musk","Khadlaj 25 Experience","Khadlaj 25 Heritage","Khadlaj 25 Integrity","Khadlaj 25 Loyalty","Khadlaj 25 Trust","Le Prestige Bold","Le Prestige Empress","Le Prestige King","Le Prestige Royal","Maison Creation De Reve","Maison Epoque Artistique","Maison Flor Oud","Maison L'Imaginaire","Maison L'Or Noir","Musk Pure Musk Blend","Mystical Indian Oud Pure","Oud Pure Oud Barakat","Oud Pure Oud Galazaid","Oud Pure Oud Jumeirah","Wild Indonesian Oud","Nafais Magrib","Nafais Sharq","Nuha","Nuha Bon Bon","Nuha Cherry Blush","Nuha Vanilla Pearl","Onyx Galaxy","Onyx Gold","Onyx Silver","Oud Pour Blueberry","Oud Pour Klassik","Panache Angel Dust","Panache Eleganza","Shiyaaka Blue","Shiyaaka For Men","Shiyaaka Gold","Shiyaaka Rose Gold","Shiyaaka Shadow","Shiyaaka Sky","Shiyaaka Snow","Stellar Musk","Stellar Oud","Valor Chivalry","Valor Enigma","Valor Honor","Valor Mystique","Azure Velvet","Cream Velvet","Peach Velvet","Aaliya","Al Riyan","Alf Wardat","Amber Pure","Ana Wa Anta","Anabia Blue","Anabia Red","Arabian Treasure","Azaari","Ghazlaan","Haneen Gold","Ibhaar","Jameel","Lulu Al Khaleej","Malika Red","Nagham","Oud & Musk","Raniya","Rasha","Rimaal Brown","Roohi Wa Roohak Gold","Safari Gold","Shamookh Gold","Shamookh Silver"]
        products = [
            row for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Khadlaj"
        ]
        self.assertEqual(len(products), 165)
        def normalize_name(value):
            return "".join(char.casefold() for char in str(value) if char.isalnum())

        names = set()
        for row in products:
            names.add(normalize_name(row.get("canonical_name")))
            names.update(normalize_name(alias) for alias in row.get("aliases", []))
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(normalize_name(name), names)

    def test_khadlaj_perfume_oil_variants_keep_their_product_type(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand_name") == "Khadlaj"
        }
        variants = CATALOG.get("variants", [])
        expected = {
            "Maya": (20, "Perfume Oil"),
            "Kayaan Gold": (20, "Perfume Oil"),
            "Johayna Green": (20, "Perfume Oil"),
            "Pink Musk": (20, "Perfume Oil"),
            "Purple Musk": (20, "Perfume Oil"),
            "Hareem Al Sultan Blue": (35, "Perfume Oil"),
            "Hareem Al Sultan Silver": (35, "Perfume Oil"),
        }
        for name, (size_ml, product_type) in expected.items():
            with self.subTest(name=name):
                row = products[name]
                self.assertEqual(row.get("product_type"), product_type)
                matches = [
                    variant for variant in variants
                    if variant.get("product_id") == row["product_id"]
                    and variant.get("size_ml") == size_ml
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("product_type"), product_type)


if __name__ == "__main__":
    unittest.main()
