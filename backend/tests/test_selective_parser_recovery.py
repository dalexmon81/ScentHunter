"""Tests for capped recovery of known, corrected parser-call failures."""
import sqlite3
import unittest

import recover_stale_parser_errors as recovery


class SelectiveParserRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE hydration_queue (
                store TEXT, url TEXT, state TEXT, attempts INTEGER,
                last_error TEXT, last_finished_at REAL,
                PRIMARY KEY(store, url)
            );
            CREATE TABLE store_urls (
                store TEXT, url TEXT, active INTEGER,
                PRIMARY KEY(store, url)
            );
        """)

    def tearDown(self):
        self.conn.close()

    def add_row(self, store, url, error, state="DEAD"):
        self.conn.execute(
            "INSERT INTO hydration_queue VALUES(?,?,?,?,?,?)",
            (store, url, state, 8, error, 100.0),
        )
        self.conn.execute(
            "INSERT INTO store_urls VALUES(?,?,1)",
            (store, url),
        )
        self.conn.commit()

    def test_only_one_verified_parfumzentrum_fragrance_url_is_eligible(self):
        allowed = next(iter(recovery.PARFUMZENTRUM_RECOVERY_ALLOWLIST))
        valid_error = (
            "ERROR:RuntimeError: product_parser_not_found;http_status=200;"
            "bytes=229236;primary_parser=none;secondary_parser=none;"
            "jsonld_products=1;h1='Berdoues Monoï & Tiaré Eau De Toilette 100 ml (unisex)'"
        )
        self.add_row("parfumzentrum", allowed, valid_error)
        # Similar parser errors for non-fragrance products must remain DEAD.
        self.add_row(
            "parfumzentrum",
            "https://www.parfum-zentrum.de/bruno-banani-made-for-women-deodorant-im-glas-75-ml-woman_z623137/",
            "product_parser_not_found;http_status=200;jsonld_products=1;"
            "h1='Bruno Banani Made for Women Deodorant im Glas 75 ml'",
        )

        plan = recovery.build_recovery_plan(self.conn, now=1234, limit_per_store=10)
        pz_items = [item for item in plan if item["store"] == "parfumzentrum"]
        self.assertEqual(len(pz_items), 1)
        self.assertEqual(pz_items[0]["url"], allowed)
        self.assertEqual(pz_items[0]["previous_state"], "DEAD")
        self.assertEqual(pz_items[0]["new_state"], "PENDING")
        self.assertEqual(pz_items[0]["reason"], "known_parser_call_error_fixed_in_current_code")

    def test_only_verified_easycosmetic_product_parser_errors_are_eligible(self):
        url = "https://www.easycosmetic.de/guerlain/lhomme-ideal/guerlain-lhomme-ideal-parfum.aspx"
        valid_error = (
            "ERROR:RuntimeError: product_parser_not_found;http_status=200;"
            "bytes=79018;primary_parser=none;secondary_parser=none;"
            "jsonld_products=1;parser_error=None;h1='Guerlain L'Homme Ideal Parfum (100 ml)'"
        )
        self.add_row("easycosmetic", url, valid_error)
        self.add_row(
            "easycosmetic",
            "https://www.easycosmetic.be/guerlain/lhomme-ideal/guerlain-lhomme-ideal-parfum.aspx",
            valid_error,
        )
        self.add_row(
            "easycosmetic",
            "https://www.easycosmetic.de/guerlain/lhomme-ideal/guerlain-lhomme-ideal-parfum-403.aspx",
            "product_parser_not_found;http_status=403;jsonld_products=1;h1='Guerlain'",
        )
        plan = recovery.build_recovery_plan(self.conn, now=1234, limit_per_store=10)
        items = [item for item in plan if item["store"] == "easycosmetic"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], url)
        self.assertEqual(items[0]["reason"], "known_easycosmetic_parser_adapter_now_available")

    def test_parfumzentrum_allowlist_requires_http_200_and_jsonld(self):
        allowed = next(iter(recovery.PARFUMZENTRUM_RECOVERY_ALLOWLIST))
        self.add_row(
            "parfumzentrum",
            allowed,
            "product_parser_not_found;http_status=403;jsonld_products=1",
        )
        plan = recovery.build_recovery_plan(self.conn, now=1234, limit_per_store=10)
        self.assertFalse(any(item["store"] == "parfumzentrum" for item in plan))


if __name__ == "__main__":
    unittest.main()
