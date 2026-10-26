"""Regression tests for bounded Deloox discovery and catalog hydration."""
import re
import unittest

from scrapers.deloox import scraper as deloox
from scrapers.parfumzentrum import scraper as parfumzentrum


class CatalogHydrationTests(unittest.TestCase):
    def test_parfumzentrum_internal_sku_suffix_is_stripped(self):
        query = "Berdoues Monoi Tiare Eau de Toilette 100 ml_z904294"
        normalized = re.sub(r"_?z\d+\s*$", "", query, flags=re.I).strip()
        self.assertEqual(normalized, "Berdoues Monoi Tiare Eau de Toilette 100 ml")

    def test_parfumzentrum_known_url_adapter_parses_jsonld_price(self):
        url = "https://www.parfum-zentrum.de/berdoues-monoi-tiare-eau-de-toilette-100-ml-unisex_z904294/"
        html = """<!doctype html><html><head>
        <script type="application/ld+json">{
          "@context":"https://schema.org",
          "@type":"Product",
          "name":"Berdoues Monoi & Tiare Eau de Toilette 100 ml",
          "brand":{"@type":"Brand","name":"Berdoues"},
          "sku":"pz-904294",
          "offers":{"@type":"Offer","price":"29.40","priceCurrency":"EUR",
                    "availability":"https://schema.org/InStock"}
        }</script></head><body><h1>Berdoues Monoï &amp; Tiaré Eau De Toilette 100 ml (unisex)</h1></body></html>"""
        product = parfumzentrum.extract_product_page(
            None, url,
            query="Berdoues Monoi Tiare Eau de Toilette 100 ml_z904294",
            html=html,
        )
        self.assertIsNotNone(product)
        self.assertEqual(product["name"], "Berdoues Monoi & Tiare Eau de Toilette 100 ml")
        self.assertEqual(product["price_num"], 29.4)
        self.assertEqual(product["availability"], "in_stock")

    def test_deloox_candidate_extractor_skips_assets_and_keeps_product_links(self):
        html = """<html><body>
        <a href="/product/12345/maison-example-eau-de-parfum-100-ml.html">Maison Example Eau de Parfum 100 ml</a>
        <a href="/product/12345/maison-example-100.jpg">product image</a>
        <div data-product-url="/product/67890/maison-example-eau-de-toilette-50-ml.html">Maison Example Eau de Toilette 50 ml</div>
        </body></html>"""
        urls = deloox._candidate_product_urls(
            html, "Maison Example", accept_all_products=False,
            base_url="https://www.deloox.be",
        )
        self.assertIn("https://www.deloox.be/product/12345/maison-example-eau-de-parfum-100-ml.html", urls)
        self.assertIn("https://www.deloox.be/product/67890/maison-example-eau-de-toilette-50-ml.html", urls)
        self.assertFalse(any(url.endswith(".jpg") for url in urls))


class FamilyRegistryBaselineTests(unittest.TestCase):
    def test_hawas_family_registry_contains_thirty_distinct_canonical_variants(self):
        """Protect the curated Hawas family registry baseline, not fabricated offers."""
        import json
        from pathlib import Path

        registry_path = Path(__file__).resolve().parents[1] / "family_registry.json"
        with registry_path.open(encoding="utf-8") as handle:
            registry = json.load(handle)

        families = registry.get("families", [])
        hawas = next(
            (family for family in families if family.get("family_id") == "rasasi_hawas"),
            None,
        )
        self.assertIsNotNone(hawas, "Rasasi Hawas family must remain registered")

        canonical_names = [
            str(product.get("canonical_name") or "").strip()
            for product in hawas.get("products", [])
            if isinstance(product, dict)
        ]
        canonical_names = [name for name in canonical_names if name]
        self.assertEqual(len(canonical_names), 30)
        self.assertEqual(len({name.casefold() for name in canonical_names}), 30)


class FamilyRegistryBaselineTests(unittest.TestCase):
    def test_hawas_family_registry_contains_thirty_distinct_canonical_variants(self):
        """Protect the curated Hawas family registry baseline, not fabricated offers."""
        import json
        from pathlib import Path

        registry_path = Path(__file__).resolve().parents[1] / "family_registry.json"
        with registry_path.open(encoding="utf-8") as handle:
            registry = json.load(handle)

        families = registry.get("families", [])
        hawas = next(
            (family for family in families if family.get("family_id") == "rasasi_hawas"),
            None,
        )
        self.assertIsNotNone(hawas, "Rasasi Hawas family must remain registered")

        canonical_names = [
            str(product.get("canonical_name") or "").strip()
            for product in hawas.get("products", [])
            if isinstance(product, dict)
        ]
        canonical_names = [name for name in canonical_names if name]
        self.assertEqual(len(canonical_names), 30)
        self.assertEqual(len({name.casefold() for name in canonical_names}), 30)



    def test_hawas_broad_query_identity_cards_preserve_all_registered_variants(self):
        """A completed broad-family search must retain all registry cards alongside real offers."""
        import json
        import sys
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parents[1]
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        import main as app_main

        with (backend_dir / "family_registry.json").open(encoding="utf-8") as handle:
            registry = json.load(handle)
        registry_family = next(
            family for family in registry.get("families", [])
            if family.get("family_id") == "rasasi_hawas"
        )

        real_matcher = app_main.PRODUCT_MATCHER
        self.assertIsNotNone(real_matcher)

        class FamilyOnlyMatcher:
            def _family_for_query(self, query):
                if query.strip().casefold() not in {"hawas", "rasasi hawas"}:
                    return None
                return real_matcher._normalize_family_registry({"families": [registry_family]})[0]

            def _requested_variant(self, query, family):
                return None

            def _build_family_result(self, offer, family, variant):
                return {
                    "catalog_id": "family-registry:" + variant["canonical_name"].casefold(),
                    "canonical_brand": family["brand"],
                    "family_name": "Hawas",
                    "canonical_name": variant["canonical_name"],
                    "canonical_image": variant.get("canonical_image") or "",
                }

        family_matcher = FamilyOnlyMatcher()
        family = family_matcher._family_for_query("Hawas")
        job_id = "test-hawas-family-snapshot"
        priced_names = {"Hawas Ice", "Hawas Black", "Hawas Kobra"}
        existing_groups = []
        for name in sorted(priced_names):
            variant = next(item for item in family["variants"] if item["canonical_name"] == name)
            identity = family_matcher._build_family_result({}, family, variant)
            existing_groups.append({
                "catalog_id": identity["catalog_id"],
                "brand": "Rasasi",
                "canonical_brand": "Rasasi",
                "name": name,
                "canonical_name": name,
                "family": "Hawas",
                "variant": name,
                "offers": [{
                    "name": name,
                    "price_num": 25.0,
                    "url": "https://example.invalid/product",
                    "store": "Fixture store",
                }],
            })

        with app_main.JOBS_LOCK:
            previous = app_main.JOBS.get(job_id)
            previous_matcher = app_main.PRODUCT_MATCHER
            app_main.PRODUCT_MATCHER = family_matcher
            app_main.JOBS[job_id] = {
                "query": "Hawas",
                "started_at": 1.0,
                "completed": True,
                "status": "completed",
                "elapsed": 0.1,
                "results": existing_groups,
                "offers": [offer for group in existing_groups for offer in group["offers"]],
                "unresolved_offers": [],
                "errors": {},
                "stores": {},
                "identity_scope": [],
                "dedupe_diagnostics": [],
                "collect_elapsed": 0.05,
                "dedupe_elapsed": 0.01,
                "aggregate_elapsed": 0.01,
                "atomic_results": True,
            }
        try:
            snapshot = app_main._snapshot(job_id)
            names = {group["canonical_name"] for group in snapshot["results"]}
            expected = {
                str(product.get("canonical_name") or "").strip()
                for product in registry_family.get("products", [])
                if str(product.get("canonical_name") or "").strip()
            }
            self.assertEqual(expected, names)
            self.assertEqual(snapshot["count"], 30)

            actual_priced = {
                group["canonical_name"] for group in snapshot["results"]
                if group.get("offers")
            }
            self.assertEqual(actual_priced, priced_names)
            self.assertTrue(all(
                group.get("identity_only")
                for group in snapshot["results"]
                if group["canonical_name"] not in actual_priced
            ))
        finally:
            with app_main.JOBS_LOCK:
                if previous is None:
                    app_main.JOBS.pop(job_id, None)
                else:
                    app_main.JOBS[job_id] = previous
                app_main.PRODUCT_MATCHER = previous_matcher


if __name__ == "__main__":
    unittest.main()
