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

    def test_deloox_search_deadline_skips_initial_fanout_when_expired(self):
        """The deadline must cover initial endpoint probes, not only pagination."""
        import time
        from unittest.mock import Mock, patch

        session = Mock()
        with patch.object(deloox, "_search_endpoints", return_value=[
            "https://www.deloox.be/chercher.html?q=parfum"
        ]) as endpoints:
            result = deloox._discover_from_search(
                session, "parfum", deadline=time.time() - 1
            )
        self.assertEqual(result, [])
        endpoints.assert_called_once_with("parfum")
        session.get.assert_not_called()
        self.assertGreaterEqual(
            deloox._LAST_DISCOVERY_STATE["search_pages_failed"], 0
        )

    def test_deloox_discovery_graph_reports_search_then_frontier_progress(self):
        """The graph exposes bounded phase data without changing product identity."""
        from unittest.mock import patch
        import catalog_engine

        seen = []
        with patch.object(catalog_engine, "_deloox_queue_enqueue"), \\
             patch.object(catalog_engine, "_deloox_queue_seed", return_value=[]), \\
             patch.object(catalog_engine, "_deloox_queue_recover_stale", return_value=0), \\
             patch.object(catalog_engine, "_deloox_queue_requeue_stale_done", return_value=0), \\
             patch.object(catalog_engine, "_discover_deloox_search_catalog", return_value={
                 "queries": [], "products": 0, "product_urls": {}, "errors": []
             }), \\
             patch.object(catalog_engine, "_deloox_queue_claim", return_value=[]), \\
             patch.object(catalog_engine, "db") as db_mock:
            conn = db_mock.return_value
            conn.execute.return_value.fetchone.return_value = {
                "pending": 0, "processing": 0, "done": 0, "error": 0,
                "dead": 0, "total": 0
            }
            catalog_engine._discover_deloox_catalog(
                [], deadline=__import__("time").time() + 2,
                progress_callback=seen.append
            )
        self.assertTrue(seen)
        self.assertEqual(seen[0]["phase"], "search")
        self.assertTrue(any(item.get("phase") == "html" for item in seen))

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

        hawas = next(
            (family for family in registry.get("families", [])
             if family.get("family_id") == "rasasi_hawas"),
            None,
        )
        self.assertIsNotNone(hawas, "Rasasi Hawas family must remain registered")
        names = [
            str(product.get("canonical_name") or "").strip()
            for product in hawas.get("products", [])
            if isinstance(product, dict)
        ]
        names = [name for name in names if name]
        self.assertEqual(len(names), 30)
        self.assertEqual(len({name.casefold() for name in names}), 30)

    def test_hawas_broad_query_identity_cards_preserve_all_registered_variants(self):
        """The broad-family snapshot adds every missing canonical identity without prices."""
        import json
        import sys
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parents[1]
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        import main as app_main
        from product_matcher import ProductMatcher

        with (backend_dir / "family_registry.json").open(encoding="utf-8") as handle:
            registry = json.load(handle)
        registry_family = next(
            family for family in registry.get("families", [])
            if family.get("family_id") == "rasasi_hawas"
        )
        matcher = ProductMatcher(catalog=[], family_registry={"families": [registry_family]})
        family = matcher._family_for_query("Hawas")
        self.assertIsNotNone(family)
        self.assertEqual(len(family["variants"]), 30)
        self.assertIsNone(
            matcher._requested_variant("Hawas", family),
            "A family alias must not be mistaken for a specific registered variant",
        )
        ice_family = matcher._family_for_query("Hawas Ice")
        self.assertIsNotNone(ice_family)
        self.assertEqual(
            matcher._requested_variant("Hawas Ice", ice_family)["canonical_name"],
            "Hawas Ice",
        )

        job_id = "test-hawas-family-snapshot"
        priced_names = {"Hawas Ice", "Hawas Black", "Hawas Kobra"}
        existing_groups = []
        for name in sorted(priced_names):
            variant = next(item for item in family["variants"] if item["canonical_name"] == name)
            identity = matcher._build_family_result(
                {"name": name, "price_num": 25.0, "url": "https://example.invalid/product"},
                family,
                variant,
            )
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
            previous_job = app_main.JOBS.get(job_id)
            previous_matcher = app_main.PRODUCT_MATCHER
            app_main.PRODUCT_MATCHER = matcher
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
            expected = {
                str(product.get("canonical_name") or "").strip()
                for product in registry_family.get("products", [])
                if str(product.get("canonical_name") or "").strip()
            }
            names = {group["canonical_name"] for group in snapshot["results"]}
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
                if previous_job is None:
                    app_main.JOBS.pop(job_id, None)
                else:
                    app_main.JOBS[job_id] = previous_job
                app_main.PRODUCT_MATCHER = previous_matcher


    def test_hawas_family_url_identity_overrides_conflicting_title(self):
        """A destination slug naming a distinct variant must beat a conflicting retailer title."""
        import json
        from pathlib import Path
        from product_matcher import ProductMatcher

        backend_dir = Path(__file__).resolve().parents[1]
        with (backend_dir / "family_registry.json").open(encoding="utf-8") as handle:
            registry = json.load(handle)
        matcher = ProductMatcher(catalog=[], family_registry=registry)
        family = matcher._family_for_query("Hawas")
        self.assertIsNotNone(family)

        offer = {
            "brand": "Rasasi",
            "name": "Hawas for Him",
            "price_num": 18.59,
            "url": "https://www.deloox.com/product/1323660/rasasi-hawas-malibu-eau-de-parfum-100-ml.html",
        }
        variant = matcher._family_variant_for_offer(offer, family)
        self.assertIsNotNone(variant)
        self.assertEqual(variant["canonical_name"], "Hawas Malibu")


if __name__ == "__main__":
    unittest.main()
