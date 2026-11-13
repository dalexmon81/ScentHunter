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
            "url": "https://www.anrdoezrs.net/click-1-2?url=https%3A%2F%2Fnotino.fr%2Fp",
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

    def test_notino_cj_replaces_unpriced_legacy_generic_url_without_gtin(self):
        legacy = {
            "store": "notino", "catalog_id": "hawas-diva",
            "canonical_name": "Hawas Diva", "name": "Hawas Diva",
            "size_ml": 100, "variant": "Eau de Parfum",
            "price": None, "price_num": None,
            "url": "https://www.notino.fr/rasasi/hawas-diva/",
        }
        cj = {
            "store": "notino", "catalog_id": "hawas-diva",
            "canonical_name": "Hawas Diva", "name": "Hawas Diva",
            "size_ml": 100, "variant": "Eau de Parfum",
            "gtin": "614514331036", "price": 26.77, "price_num": 26.77,
            "currency": "EUR",
            "url": "https://www.kqzyfj.com/click-123?url=https%3A%2F%2Fwww.notino.fr%2Frasasi%2Fhawas-diva%2Fp-123%2F",
            "source": "cj_notino_fr_feed",
        }

        self.assertEqual(dedupe_results([legacy, cj]), [cj])

    def test_notino_unpriced_standalone_row_is_not_public(self):
        unpriced = {
            "store": "Notino", "catalog_id": "hawas-chrome",
            "name": "Hawas Chrome", "canonical_name": "Hawas Chrome",
            "size_ml": 100, "url": "https://www.notino.fr/rasasi/hawas-chrome/",
            "price": None, "price_num": None,
        }
        self.assertEqual(dedupe_results([unpriced]), [])

    def test_notino_fallback_does_not_merge_different_valid_gtins(self):
        first = {
            "store": "notino", "catalog_id": "hawas",
            "name": "Hawas", "canonical_name": "Hawas",
            "size_ml": 100, "variant": "Eau de Parfum",
            "gtin": "6290360375694", "price_num": 30.00,
            "url": "https://www.notino.fr/p-100/",
        }
        second = {
            **first, "gtin": "6298042001831", "price_num": 31.00,
            "url": "https://www.notino.fr/p-101/",
        }
        self.assertEqual(len(dedupe_results([first, second])), 2)

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


    def test_notino_generic_hawas_category_url_is_never_public(self):
        generic = {
            "store": "Notino", "name": "Rasasi Hawas Ice",
            "catalog_id": "hawas-ice", "size_ml": 100,
            "price_num": 32.50, "currency": "EUR",
            "url": "https://www.notino.fr/rasasi/hawas-ice/",
        }
        exact = {
            **generic,
            "url": "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum-pour-homme/p-16242201/",
            "price_num": 36.00,
            "source": "cj_notino_fr_feed",
        }
        self.assertEqual(dedupe_results([generic]), [])
        self.assertEqual(dedupe_results([generic, exact]), [exact])

    def test_notino_hawas_editions_keep_separate_exact_product_pages(self):
        editions = [
            {"store": "Notino", "name": name, "catalog_id": name.lower(),
             "size_ml": 100, "price_num": price, "currency": "EUR",
             "gtin": gtin, "url": f"https://www.notino.fr/rasasi/{slug}/p-{pid}/"}
            for name, price, gtin, slug, pid in [
                ("Hawas Ice", 36.00, "614514331040", "hawas-ice-eau-de-parfum-pour-homme", "16242201"),
                ("Hawas Elixir", 26.35, "614514331057", "hawas-elixir-eau-de-parfum-mixte", "16306315"),
                ("Hawas La Mer", 32.30, "614514331279", "hawas-la-mer-eau-de-parfum-pour-homme", "16403740"),
                ("Hawas Majestic", 32.21, "614514331118", "hawas-majestic-eau-de-parfum-mixte", "16403346"),
            ]
        ]
        self.assertEqual(dedupe_results(editions), editions)

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

        cj["url"] = "https://www.kqzyfj.com/click-1-2?url=https%3A%2F%2Fwww.notino.fr%2Ffrench-avenue%2Fliquid-brun%2Fp-16289640%2F"
        legacy["url"] = "https://www.notino.fr/french-avenue/liquid-brun/p-16289640/"
        legacy["price_num"] = 34.90
        merged = _merge_notino_phase2_offers([cj], [legacy])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "cj_notino_fr_feed")
        self.assertEqual(merged[0]["price_num"], 34.90)
        self.assertEqual(merged[0]["url"], cj["url"])

    def test_notino_cj_merge_keeps_different_valid_gtins(self):
        cj = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "size_ml": 100, "gtin": "6290360375694", "store": "notino",
        }
        other_gtin = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "size_ml": 100, "gtin": "6290360375601", "store": "Notino",
        }

        cj["url"] = "https://www.notino.fr/liquid-brun/p-100/"
        other_gtin["url"] = "https://www.notino.fr/liquid-brun/p-101/"
        other_gtin["price_num"] = 31.00
        merged = _merge_notino_phase2_offers([cj], [other_gtin])

        # A feed offer is withheld without a hydrated row for its exact page;
        # the unrelated edition remains separate.
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["url"], other_gtin["url"])

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

        cj["url"] = "https://www.notino.fr/liquid-brun/p-100/"
        hydrated_same = {
            "store": "notino", "url": cj["url"], "size_ml": 100,
            "price_num": 29.90, "price": "29.90 €",
        }
        merged = _merge_notino_phase2_offers(
            [cj], [hydrated_same, different_size, different_concentration]
        )

        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0]["price_num"], 29.90)
        self.assertIn(different_size, merged)
        self.assertIn(different_concentration, merged)

    def test_notino_callbacks_publish_only_after_cj_merge(self):
        cj = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "variant": "Eau de Parfum", "size_ml": 100,
            "gtin": "6290360375694", "store": "notino",
            "source": "cj_notino_fr_feed",
            "url": "https://www.kqzyfj.com/click-1-2?url=https%3A%2F%2Fwww.notino.fr%2Ffrench-avenue%2Fliquid-brun%2Fp-100%2F",
        }
        legacy = {
            "catalog_id": "SH-0030", "name": "Liquid Brun",
            "size_ml": 100, "store": "notino", "price_num": 36.70,
            "url": "https://www.notino.fr/french-avenue/liquid-brun/p-100/",
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
        self.assertEqual(len(reports[0]["results"]), 1)
        self.assertEqual(reports[0]["results"][0]["price_num"], 36.70)
        self.assertEqual(len(published_reports), 1)
        self.assertEqual(published_reports[0]["results"][0]["price_num"], 36.70)
        self.assertEqual(published_results[0]["price_num"], 36.70)

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

    def test_isolated_cj_snapshot_does_not_duplicate_untracked_feed_path(self):
        with (
            patch.dict(os.environ, {"NOTINO_CJ_STANDALONE_ENABLED": "1"}),
            patch.object(main, "catalog_search_local", return_value=[]),
            patch.object(main, "catalog_refresh_candidates", None),
            patch.object(main, "_catalog_indexed_flags", return_value={"notino": True}),
            patch.object(main.importlib, "import_module") as importer,
        ):
            main._collect_catalog_reports_isolated(
                "Liquid Brun", ["notino"], allow_live_fallback=False,
            )
        importer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
