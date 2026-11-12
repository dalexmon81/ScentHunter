"""Regression tests for retailer-offer deduplication across canonical catalog records."""

import os
import unittest
from unittest.mock import patch

import main
from main import _merge_notino_phase2_offers, _public_offer, dedupe_results, result_key


class ResultDeduplicationTests(unittest.TestCase):
    def test_public_offer_preserves_currency_and_cj_feed_source(self):
        offer = _public_offer({
            "catalog_id": "SH-0030",
            "name": "Liquid Brun",
            "brand": "French Avenue",
            "store": "notino",
            "price": 36.70,
            "price_num": 36.70,
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://www.anrdoezrs.net/click?url=https%3A%2F%2Fnotino.fr%2Fp",
            "source": "cj_notino_fr_feed",
        })

        self.assertEqual(offer["currency"], "EUR")
        self.assertEqual(offer["source"], "cj_notino_fr_feed")

    def test_same_retailer_url_is_deduplicated_across_catalog_ids(self):
        first = {
            "store": "sabina",
            "url": "https://www.sabina.com/es/product/example",
            "product_url": "https://www.sabina.com/es/product/example",
            "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml",
            "size_ml": 100,
            "price_num": 38.90,
        }
        duplicate = {
            **first,
            "catalog_id": "canonical-b",
        }

        self.assertEqual(result_key(first), result_key(duplicate))
        self.assertEqual(dedupe_results([first, duplicate]), [first])

    def test_notino_same_gtin_collapses_legacy_and_cj_urls(self):
        legacy = {
            "store": "notino",
            "url": "https://www.notino.fr/french-avenue/liquid-brun/",
            "product_url": "https://www.notino.fr/french-avenue/liquid-brun/",
            "catalog_id": "SH-0030",
            "name": "Liquid Brun",
            "gtin": "6290360375694",
            "size_ml": 100,
            "price_num": 36.70,
        }
        cj = {
            **legacy,
            "url": "https://www.anrdoezrs.net/click?url=https%3A%2F%2Fwww.notino.fr%2Fp-16289640%2F",
            "product_url": "https://www.notino.fr/french-avenue/liquid-brun-eau-de-parfum-mixte/p-16289640/",
            "source": "cj_notino_fr_feed",
        }
        self.assertEqual(result_key(legacy), result_key(cj))
        self.assertEqual(dedupe_results([cj, legacy]), [cj])
        diagnostics = []
        self.assertEqual(dedupe_results([legacy, cj], diagnostics), [cj])
        self.assertEqual(diagnostics[0]["kept"]["url"], cj["url"])
        self.assertEqual(diagnostics[0]["dropped"]["url"], legacy["url"])

    def test_notino_distinct_gtins_remain_separate(self):
        first = {
            "store": "notino", "url": "https://www.notino.fr/p-100/",
            "gtin": "6290360375694", "size_ml": 100, "price_num": 36.70,
        }
        second = {
            **first, "url": "https://www.notino.fr/p-150/",
            "gtin": "6298042001831", "size_ml": 150, "price_num": 49.90,
        }
        self.assertNotEqual(result_key(first), result_key(second))
        self.assertEqual(len(dedupe_results([first, second])), 2)

    def test_shopify_locales_collapse_only_equivalent_listings(self):
        unknown = {
            "store": "parfumcity", "url": "https://www.parfumcity.nl/fr/products/example",
            "catalog_id": "example", "variant_id": "example:100", "size_ml": 100,
            "price_num": None, "availability": "unknown",
        }
        priced = {
            **unknown, "url": "https://www.parfumcity.nl/products/example",
            "price_num": 29.90, "currency": "EUR", "availability": "in_stock",
        }
        same = {**priced, "url": "https://www.parfumcity.nl/it/products/example"}
        other_price = {**priced, "url": "https://www.parfumcity.nl/de/products/example", "price_num": 31.90}
        other_variant = {**priced, "url": "https://www.parfumcity.nl/es/products/example", "variant_id": "example:150", "size_ml": 150}
        self.assertEqual(dedupe_results([unknown, priced, same, other_price, other_variant]), [
            priced, other_price, other_variant,
        ])

    def test_distinct_sizes_of_same_retailer_url_are_preserved(self):
        first = {
            "store": "sabina",
            "url": "https://www.sabina.com/es/product/example",
            "product_url": "https://www.sabina.com/es/product/example",
            "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum",
            "size_ml": 50,
            "price_num": 29.90,
        }
        second = {
            **first,
            "catalog_id": "canonical-b",
            "size_ml": 100,
            "price_num": 38.90,
        }

        self.assertNotEqual(result_key(first), result_key(second))
        self.assertEqual(len(dedupe_results([first, second])), 2)

    def test_distinct_explicit_variant_selectors_are_preserved(self):
        first = {
            "store": "sabina",
            "url": "https://www.sabina.com/es/product/example#size-100-ml",
            "product_url": "https://www.sabina.com/es/product/example",
            "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml",
            "size_ml": 100,
        }
        second = {
            **first,
            "url": "https://www.sabina.com/es/product/example#size-200-ml",
            "catalog_id": "canonical-b",
        }

        self.assertNotEqual(result_key(first), result_key(second))
        self.assertEqual(len(dedupe_results([first, second])), 2)

    def test_tracking_parameters_do_not_create_duplicate_easycosmetic_offers(self):
        first = {
            "store": "easycosmetic",
            "url": "https://www.easycosmetic.de/p/example?utm_source=google",
            "product_url": "https://www.easycosmetic.de/p/example?utm_source=google",
            "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml",
            "size_ml": 100,
            "price_num": 25.99,
        }
        duplicate = {
            **first,
            "url": "https://easycosmetic.de/p/example?gclid=tracking",
            "product_url": "https://easycosmetic.de/p/example?gclid=tracking",
            "catalog_id": "canonical-b",
        }

        self.assertEqual(result_key(first), result_key(duplicate))
        self.assertEqual(len(dedupe_results([first, duplicate])), 1)

    def test_distinct_variant_query_parameters_are_not_collapsed(self):
        first = {
            "store": "easycosmetic",
            "url": "https://www.easycosmetic.de/p/example?variant=100",
            "product_url": "https://www.easycosmetic.de/p/example?variant=100",
            "name": "Example Eau de Parfum",
            "size_ml": 100,
        }
        second = {
            **first,
            "url": "https://www.easycosmetic.de/p/example?variant=200",
            "product_url": "https://www.easycosmetic.de/p/example?variant=200",
        }

        self.assertNotEqual(result_key(first), result_key(second))
        self.assertEqual(len(dedupe_results([first, second])), 2)


    def test_same_easycosmetic_name_size_price_different_urls_is_deduplicated(self):
        first = {
            "store": "easycosmetic", "url": "https://www.easycosmetic.de/p/example-a",
            "product_url": "https://www.easycosmetic.de/p/example-a", "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml", "size_ml": 100, "price_num": 25.99,
        }
        duplicate = {**first, "url": "https://www.easycosmetic.de/p/example-b",
                     "product_url": "https://www.easycosmetic.de/p/example-b", "catalog_id": "canonical-b"}
        self.assertEqual(len(dedupe_results([first, duplicate])), 1)

    def test_same_sabina_name_size_price_different_urls_is_deduplicated(self):
        first = {
            "store": "sabina", "url": "https://www.sabina.com/es/product/example-a",
            "product_url": "https://www.sabina.com/es/product/example-a", "catalog_id": "canonical-a",
            "name": "Example Eau de Parfum 100 ml", "size_ml": 100, "price_num": 38.90,
        }
        duplicate = {**first, "url": "https://www.sabina.com/es/product/example-b",
                     "product_url": "https://www.sabina.com/es/product/example-b", "catalog_id": "canonical-b"}
        self.assertEqual(len(dedupe_results([first, duplicate])), 1)

    def test_same_store_name_size_different_price_is_preserved(self):
        first = {"store": "sabina", "url": "https://www.sabina.com/es/product/example-a",
                 "name": "Example Eau de Parfum", "size_ml": 100, "price_num": 38.90}
        second = {**first, "url": "https://www.sabina.com/es/product/example-b", "price_num": 39.90}
        self.assertEqual(len(dedupe_results([first, second])), 2)


    def test_easycosmetic_same_price_deduplicates_when_size_metadata_missing(self):
        first = {"store": "easycosmetic", "url": "https://www.easycosmetic.de/p/a",
                 "name": "Example Eau de Parfum", "price_num": 25.99}
        duplicate = {"store": "easycosmetic", "url": "https://www.easycosmetic.de/p/b",
                     "name": "Example Eau de Parfum 100 ml", "price_num": 25.99}
        self.assertEqual(len(dedupe_results([first, duplicate])), 1)


    def test_notino_cj_offer_replaces_legacy_row_without_gtin(self):
        cj = {
            "catalog_id": "SH-0030", "brand": "French Avenue",
            "name": "Liquid Brun", "variant": "Eau de Parfum",
            "size_ml": 100, "price_num": 36.70,
            "gtin": "6290360375694", "store": "notino",
            "url": "https://affiliate.example/cj-clickout",
            "source": "cj_notino_fr_feed",
        }
        legacy = {
            "catalog_id": "SH-0030", "brand": "French Avenue",
            "name": "Liquid Brun", "size_ml": 100,
            "price_num": 36.70, "store": "Notino",
            "variant_id": "SH-0030:100",
            "url": "https://www.notino.fr/french-avenue/liquid-brun/",
        }

        merged = _merge_notino_phase2_offers([cj], [legacy])

        self.assertEqual(merged, [cj])
        self.assertEqual(merged[0]["source"], "cj_notino_fr_feed")

    def test_notino_cj_merge_keeps_different_valid_gtins(self):
        cj = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "size_ml": 100, "gtin": "6290360375694", "store": "notino",
        }
        other_gtin = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "size_ml": 100, "gtin": "6290360375601", "store": "Notino",
        }

        merged = _merge_notino_phase2_offers([cj], [other_gtin])

        self.assertEqual(len(merged), 2)

    def test_notino_cj_merge_preserves_distinct_sizes_and_concentrations(self):
        cj = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "variant": "Eau de Parfum", "size_ml": 100,
            "gtin": "6290360375694", "store": "notino",
        }
        different_size = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "size_ml": 150, "store": "Notino",
        }
        different_concentration = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "variant": "Extrait de Parfum", "size_ml": 100,
            "store": "Notino",
        }

        merged = _merge_notino_phase2_offers(
            [cj], [different_size, different_concentration]
        )

        self.assertEqual(len(merged), 3)
        self.assertIn(different_size, merged)
        self.assertIn(different_concentration, merged)

    def test_notino_callbacks_publish_only_after_cj_merge(self):
        cj = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "variant": "Eau de Parfum", "size_ml": 100,
            "gtin": "6290360375694", "store": "notino",
            "source": "cj_notino_fr_feed",
        }
        legacy = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "size_ml": 100, "store": "notino",
            "url": "https://www.notino.fr/french-avenue/liquid-brun/",
        }
        legacy_report = {
            "store": "notino", "status": "success", "verified": True,
            "results": [legacy], "count": 1,
        }
        published_reports = []
        published_results = []

        def collect(*args, **kwargs):
            kwargs["on_report"](legacy_report)
            kwargs["on_result"](legacy)
            return [legacy_report]

        with (
            patch.object(main, "CATALOG_ENGINE_AVAILABLE", True),
            patch.object(main, "catalog_search_local", lambda *args, **kwargs: []),
            patch(
                "app.services.notino_phase2_search.search_notino_phase2",
                return_value=[cj],
            ),
            patch.object(main, "_collect_catalog_reports_isolated", side_effect=collect),
        ):
            reports = main.collect_store_reports_isolated(
                "Liquid Brun", ["notino"],
                on_report=published_reports.append,
                on_result=published_results.append,
            )

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["results"], [cj])
        self.assertEqual(len(published_reports), 1)
        self.assertEqual(published_reports[0]["results"], [cj])
        self.assertEqual(published_results, [cj])

    def test_notino_live_fallback_is_disabled_by_default(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(main, "CATALOG_ENGINE_AVAILABLE", True),
            patch.object(main, "catalog_search_local", lambda *args, **kwargs: []),
            patch(
                "app.services.notino_phase2_search.search_notino_phase2",
                return_value=[],
            ),
            patch(
                "main._collect_catalog_reports_isolated",
                return_value=[],
            ) as collect,
        ):
            main.collect_store_reports_isolated("Hawas", ["notino"])

        self.assertFalse(collect.call_args.kwargs["allow_live_fallback"])

    def test_notino_legacy_results_are_published_when_feed_has_no_matches(self):
        legacy = {"store": "notino", "name": "Example", "url": "https://notino.fr/example"}
        report = {"store": "notino", "results": [legacy], "count": 1}
        published = []
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(main, "CATALOG_ENGINE_AVAILABLE", True),
            patch.object(main, "catalog_search_local", lambda *args, **kwargs: []),
            patch("app.services.notino_phase2_search.search_notino_phase2", return_value=[]),
            patch.object(main, "_collect_catalog_reports_isolated", return_value=[report]),
        ):
            main.collect_store_reports_isolated("Example", ["notino"], on_result=published.append)
        self.assertEqual(published, [legacy])



    def test_catalog_search_includes_authorized_notino_feed_variants(self):
        feed_offer = {
            "store": "notino", "shop": "Notino",
            "brand": "French Avenue", "name": "Liquid Brun Eau de Parfum",
            "price": "36.70 €", "price_num": 36.70, "currency": "EUR",
            "availability": "in_stock", "available": True,
            "size_ml": 100, "concentration": "Eau de Parfum",
            "url": "https://www.notino.fr/french-avenue/liquid-brun/p-123/",
            "gtin": "6290360375694", "source": "cj_viv_authorized_xml",
        }
        feed_module = type("FeedModule", (), {
            "search_feed": staticmethod(lambda query: {
                "status": "success", "verified": True,
                "results": [feed_offer],
                "details": {"catalog_candidates": 9533, "matched_offers": 1},
            })
        })()
        resolved = {
            **feed_offer, "store": "Notino", "shop": "Notino",
            "_match_status": "matched", "catalog_id": "SH-TEST",
            "canonical_name": "Liquid Brun",
        }

        with (
            patch.object(main, "catalog_search_local", lambda *args, **kwargs: []),
            patch.object(main, "catalog_refresh_candidates", None),
            patch.object(main, "_catalog_indexed_flags", lambda stores: {"notino": True}),
            patch.object(main.importlib, "import_module", return_value=feed_module),
            patch.object(main, "_resolve_offer_identity", return_value=resolved),
        ):
            reports = main._collect_catalog_reports_isolated(
                "Liquid Brun", ["notino"], allow_live_fallback=False,
            )

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["count"], 1)
        self.assertEqual(reports[0]["results"][0]["source"], "cj_viv_authorized_xml")
        self.assertEqual(reports[0]["results"][0]["catalog_id"], "SH-TEST")


if __name__ == "__main__":
    unittest.main()
