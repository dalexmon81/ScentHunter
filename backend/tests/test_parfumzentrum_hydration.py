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

    def test_parfumzentrum_ignores_placeholder_price_and_uses_valid_jsonld_price(self):
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
        }</script></head><body>
        <h1>Berdoues Monoi &amp; Tiaré Eau De Toilette 100 ml</h1>
        <div class="product-price"><span itemprop="price" content="1.00">1,00 €</span></div>
        </body></html>"""
        product = parfumzentrum.extract_product_page(
            None, url, query="Berdoues Monoi Tiare Eau de Toilette 100 ml", html=html
        )
        self.assertIsNotNone(product)
        self.assertEqual(product["price_num"], 29.4)

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

    def test_deloox_search_budget_rotates_query_and_limits_each_run(self):
        """One generic query per run rotates without making prices or identity part of discovery."""
        from unittest.mock import patch
        import catalog_engine

        result = {
            "queries": [{"query": "parfum", "returned": 1, "added": 1}],
            "products": 1,
            "product_urls": {"https://www.deloox.com/product/1000001/test-eau-de-parfum-100-ml.html": ""},
            "errors": [],
        }
        class FakeConnection:
            def __init__(self):
                self.values = {"deloox_search_query_offset": "0"}
                self.closed = False
            def execute(self, query, params=()):
                class Cursor:
                    def __init__(self, row=None):
                        self.row = row
                    def fetchone(self):
                        return self.row
                if "SELECT value FROM catalog_discovery_meta" in query:
                    value = self.values.get(params[0])
                    return Cursor({"value": value} if value is not None else None)
                if "INSERT INTO catalog_discovery_meta" in query:
                    self.values[params[0]] = params[1]
                return Cursor()
            def commit(self):
                pass
            def close(self):
                self.closed = True

        conn = FakeConnection()
        with patch.object(catalog_engine, "db", return_value=conn), \
             patch.object(catalog_engine, "_deloox_queue_allowed", return_value=True), \
             patch.object(catalog_engine, "_deloox_persist_products") as persist, \
             patch("scrapers.deloox.scraper._discover", return_value=list(result["product_urls"])) as discover:
            first = catalog_engine._discover_deloox_search_catalog(
                deadline=__import__("time").time() + 2, max_queries=1
            )
            self.assertEqual(len(first["queries"]), 1)
            self.assertEqual(first["products"], 1)
            self.assertEqual(conn.values["deloox_search_query_offset"], "1")

            second = catalog_engine._discover_deloox_search_catalog(
                deadline=__import__("time").time() + 2, max_queries=1
            )
            self.assertEqual(len(second["queries"]), 1)
            self.assertEqual(conn.values["deloox_search_query_offset"], "2")

        called_queries = [call.args[1] for call in discover.call_args_list]
        self.assertEqual(called_queries, ["parfum", "perfume"])
        self.assertEqual(persist.call_count, 2)

    def test_deloox_search_budget_reserves_time_for_frontier(self):
        """Search uses a shorter budget than the durable frontier budget."""
        import time
        from unittest.mock import patch
        import catalog_engine

        observed = []
        search_result = {"queries": [], "products": 0, "product_urls": {}, "errors": []}
        with patch.object(catalog_engine, "_deloox_queue_enqueue"), \
             patch.object(catalog_engine, "_deloox_queue_seed", return_value=[]), \
             patch.object(catalog_engine, "_deloox_queue_recover_stale", return_value=0), \
             patch.object(catalog_engine, "_deloox_queue_requeue_stale_done", return_value=0), \
             patch.object(catalog_engine, "_discover_deloox_search_catalog", side_effect=lambda deadline, progress_callback=None, max_queries=None: observed.append((deadline, max_queries)) or search_result), \
             patch.object(catalog_engine, "_deloox_queue_claim", return_value=[]), \
             patch.object(catalog_engine, "db") as db_mock:
            conn = db_mock.return_value
            conn.execute.return_value.fetchone.return_value = {
                "pending": 0, "processing": 0, "done": 0, "error": 0,
                "dead": 0, "total": 0
            }
            start = time.time()
            catalog_engine._discover_deloox_catalog(
                [], deadline=start + 100, progress_callback=lambda value: None
            )

        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][1], 1)
        self.assertLessEqual(observed[0][0], start + 25.2)

    def test_deloox_discovery_graph_reports_search_then_frontier_progress(self):
        """The graph emits search progress before crawling and HTML progress after a batch."""
        import time
        from unittest.mock import patch
        import catalog_engine

        seen = []
        queue_row = ("https://www.deloox.be/", 0, "configured_seed", "test-lease")
        fetch_result = (
            "https://www.deloox.be/",
            "https://www.deloox.be/",
            b"<html><body><a href='/en/category/12345/fragrances.html'>Fragrances</a></body></html>",
            None,
        )

        class FakeConnection:
            def __init__(self):
                self.queue_rows = []
            def execute(self, query, params=()):
                class Cursor:
                    def __init__(self, rows=None, one=None):
                        self._rows=rows or []
                        self._one=one
                    def fetchone(self):
                        return self._one
                    def fetchall(self):
                        return self._rows
                if "SELECT url,depth,priority,source" in query:
                    return Cursor(rows=[])
                if "SUM(CASE WHEN state='PENDING'" in query:
                    return Cursor(one={
                        "pending": 1, "processing": 0, "done": 0,
                        "error": 0, "dead": 0, "total": 1
                    })
                return Cursor()
            def close(self):
                pass
            def commit(self):
                pass
            def rollback(self):
                pass

        conn=FakeConnection()
        with patch.object(catalog_engine, "_deloox_queue_enqueue"), \
             patch.object(catalog_engine, "_deloox_queue_seed", return_value=[]), \
             patch.object(catalog_engine, "_deloox_queue_recover_stale", return_value=0), \
             patch.object(catalog_engine, "_deloox_queue_requeue_stale_done", return_value=0), \
             patch.object(catalog_engine, "_discover_deloox_search_catalog", return_value={
                 "queries": [], "products": 0, "product_urls": {}, "errors": []
             }), \
             patch.object(catalog_engine, "_deloox_queue_claim", side_effect=[[queue_row], []]), \
             patch.object(catalog_engine, "_fetch_html_page", return_value=fetch_result), \
             patch.object(catalog_engine, "_deloox_queue_finish"), \
             patch.object(catalog_engine, "_deloox_persist_products"), \
             patch.object(catalog_engine, "db", return_value=conn):
            catalog_engine._discover_deloox_catalog(
                [], deadline=time.time() + 2, progress_callback=seen.append
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



class StaleHydrationQueueTests(unittest.TestCase):
    """Regression checks for re-queueing previously hydrated stale products."""

    def setUp(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        import catalog_engine

        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "catalog.sqlite3"
        self._old_path = catalog_engine.DB_PATH
        catalog_engine.DB_PATH = self._path
        conn = sqlite3.connect(str(self._path))
        conn.executescript("""
        CREATE TABLE hydration_queue(
          store TEXT NOT NULL, url TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING',
          priority INTEGER NOT NULL DEFAULT 100, attempts INTEGER NOT NULL DEFAULT 0,
          available_at REAL NOT NULL DEFAULT 0, leased_until REAL, lease_token TEXT,
          first_seen_at REAL NOT NULL, last_started_at REAL, last_finished_at REAL,
          last_error TEXT, last_http_status INTEGER, PRIMARY KEY(store,url));
        CREATE TABLE store_urls(
          store TEXT NOT NULL, url TEXT NOT NULL, slug TEXT NOT NULL DEFAULT '',
          lastmod TEXT, discovered_at REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(store,url));
        CREATE TABLE store_products(
          store TEXT NOT NULL, url TEXT NOT NULL, price REAL, fetched_at REAL,
          fetch_status TEXT, PRIMARY KEY(store,url));
        CREATE TABLE store_product_variants(
          store TEXT NOT NULL, url TEXT NOT NULL, variant_key TEXT NOT NULL,
          price REAL, fetched_at REAL, PRIMARY KEY(store,url,variant_key));
        CREATE TABLE hydration_scheduler(id INTEGER PRIMARY KEY, last_store_index INTEGER NOT NULL DEFAULT 0);
        INSERT INTO hydration_scheduler(id,last_store_index) VALUES(1,0);
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        import catalog_engine
        catalog_engine.DB_PATH = self._old_path
        self._tmp.cleanup()

    def _seed(self, store, suffix, state, fetched_at, price=29.99, active=1, attempts=1):
        import sqlite3
        import catalog_engine

        url = "https://example.invalid/" + suffix
        conn = sqlite3.connect(str(catalog_engine.DB_PATH))
        conn.execute(
            "INSERT INTO store_urls(store,url,active,discovered_at) VALUES(?,?,?,?)",
            (store, url, active, 1),
        )
        conn.execute(
            """INSERT INTO hydration_queue(
                 store,url,state,attempts,available_at,first_seen_at)
               VALUES(?,?,?,?,?,?)""",
            (store, url, state, attempts, 0, 1),
        )
        conn.execute(
            "INSERT INTO store_products(store,url,price,fetched_at,fetch_status) VALUES(?,?,?,?,?)",
            (store, url, price, fetched_at, "OK"),
        )
        conn.commit()
        conn.close()
        return url

    def test_recent_done_product_is_not_requeued(self):
        import sqlite3
        import catalog_engine
        now = 2_000_000.0
        url = self._seed("deloox", "recent", "DONE", now - 60)
        self.assertEqual(catalog_engine.requeue_stale_done_hydration_tasks(16, now), 0)
        conn = sqlite3.connect(str(catalog_engine.DB_PATH))
        state = conn.execute("SELECT state FROM hydration_queue WHERE url=?", (url,)).fetchone()[0]
        conn.close()
        self.assertEqual(state, "DONE")

    def test_stale_done_product_is_requeued_without_duplicate(self):
        import sqlite3
        import catalog_engine
        now = 2_000_000.0
        url = self._seed("deloox", "stale", "DONE", now - 25 * 3600)
        self.assertEqual(catalog_engine.requeue_stale_done_hydration_tasks(16, now), 1)
        conn = sqlite3.connect(str(catalog_engine.DB_PATH))
        row = conn.execute(
            "SELECT state,attempts,priority FROM hydration_queue WHERE url=?", (url,)
        ).fetchone()
        total = conn.execute(
            "SELECT COUNT(*) FROM hydration_queue WHERE store='deloox' AND url=?", (url,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(row[0], "PENDING")
        self.assertEqual(row[1], 1)
        self.assertLessEqual(row[2], 50)
        self.assertEqual(total, 1)
        self.assertEqual(catalog_engine.requeue_stale_done_hydration_tasks(16, now), 0)

    def test_missing_price_done_product_obeys_six_hour_retry_cooldown(self):
        import sqlite3
        import catalog_engine
        now = 2_000_000.0
        recent = self._seed("deloox", "missing-recent", "DONE", now - 60, price=None)
        stale = self._seed("bplatz", "missing-stale", "DONE", now - 7 * 3600, price=None)
        self.assertEqual(catalog_engine.requeue_stale_done_hydration_tasks(16, now), 1)
        conn = sqlite3.connect(str(catalog_engine.DB_PATH))
        states = dict(conn.execute(
            "SELECT url,state FROM hydration_queue WHERE url IN (?,?)", (recent, stale)
        ).fetchall())
        conn.close()
        self.assertEqual(states[recent], "DONE")
        self.assertEqual(states[stale], "PENDING")

    def test_inactive_or_terminal_dead_rows_are_not_revived_by_stale_scheduler(self):
        import sqlite3
        import catalog_engine
        now = 2_000_000.0
        inactive = self._seed("deloox", "inactive", "DONE", now - 48 * 3600, active=0)
        dead = self._seed("bplatz", "dead", "DEAD", now - 48 * 3600)
        self.assertEqual(catalog_engine.requeue_stale_done_hydration_tasks(16, now), 0)
        conn = sqlite3.connect(str(catalog_engine.DB_PATH))
        states = dict(conn.execute(
            "SELECT url,state FROM hydration_queue WHERE url IN (?,?)", (inactive, dead)
        ).fetchall())
        conn.close()
        self.assertEqual(states[inactive], "DONE")
        self.assertEqual(states[dead], "DEAD")

    def test_retryable_error_keeps_backoff_and_terminal_http_is_dead(self):
        import sqlite3
        import catalog_engine
        now = 2_000_000.0
        retry_url = self._seed("deloox", "retry", "PROCESSING", now - 25 * 3600)
        terminal_url = self._seed("bplatz", "terminal", "PROCESSING", now - 25 * 3600)
        conn = sqlite3.connect(str(catalog_engine.DB_PATH))
        conn.execute(
            "UPDATE hydration_queue SET lease_token='retry-token',attempts=2 WHERE url=?",
            (retry_url,),
        )
        conn.execute(
            "UPDATE hydration_queue SET lease_token='terminal-token',attempts=1 WHERE url=?",
            (terminal_url,),
        )
        conn.commit()
        conn.close()
        with patch.object(catalog_engine, "db", wraps=catalog_engine.db):
            catalog_engine._queue_mark_error(
                {"store": "deloox", "url": retry_url, "lease_token": "retry-token"},
                "TimeoutError: temporary network failure",
            )
            catalog_engine._queue_mark_error(
                {"store": "bplatz", "url": terminal_url, "lease_token": "terminal-token"},
                "HTTP 404",
                http_status=404,
            )
        conn = sqlite3.connect(str(catalog_engine.DB_PATH))
        retry = conn.execute("SELECT state,available_at,attempts FROM hydration_queue WHERE url=?", (retry_url,)).fetchone()
        terminal = conn.execute("SELECT state FROM hydration_queue WHERE url=?", (terminal_url,)).fetchone()
        conn.close()
        self.assertEqual(retry[0], "ERROR")
        self.assertGreater(retry[1], now)
        self.assertEqual(retry[2], 2)
        self.assertEqual(terminal[0], "DEAD")


if __name__ == "__main__":
    unittest.main()
