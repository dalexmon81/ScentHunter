"""Offline parser regressions for Orioudh and PerfumeMarket.

All inputs are synthetic fixtures. These tests do not contact either retailer.
The adapters have different output contracts, so assertions stay retailer-specific.
"""
from scrapers.orioudh import scraper as orioudh
from scrapers.perfumemarket import scraper as perfume_market


class _JsonResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.closed = False

    def json(self):
        return self._payload

    def close(self):
        self.closed = True


class _JsonSession:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return _JsonResponse(self.payload)


def test_orioudh_shopify_json_maps_variant_cents_gtin_size_and_stock():
    session = _JsonSession({
        "id": 12345,
        "title": "Liquid Brun Eau de Parfum",
        "vendor": "French Avenue",
        "featured_image": "//cdn.example.test/liquid-brun.jpg",
        "variants": [
            {
                "id": 501,
                "title": "100 ml",
                "sku": "FA-LB-100",
                "barcode": "6290360599999",
                "price": 3185,
                "available": True,
            },
            {
                "id": 502,
                "title": "100 ml tester",
                "sku": "FA-LB-TESTER",
                "barcode": "",
                "price": 0,
                "available": False,
            },
        ],
    })

    rows = orioudh._extract_product(
        session,
        "https://orioudh.com/products/liquid-brun",
        "Liquid Brun",
    )

    assert session.urls == ["https://orioudh.com/products/liquid-brun.js"]
    assert len(rows) == 1
    row = rows[0]
    assert row["store"] == "Orioudh"
    assert row["source"]["source_brand"] == "French Avenue"
    assert row["identity"]["gtin"]["value"] == "6290360599999"
    assert row["identity"]["store_variant_id"]["value"] == 501
    assert row["attributes"]["size_ml"]["value"] == 100
    assert row["attributes"]["concentration"]["value"] == "Eau de Parfum"
    assert row["offer"] == {
        "price": 31.85,
        "currency": "EUR",
        "availability": "in_stock",
    }


def test_orioudh_availability_keeps_unknown_distinct_from_out_of_stock():
    assert orioudh._availability(True) == "in_stock"
    assert orioudh._availability(False) == "out_of_stock"
    assert orioudh._availability(None) == "unknown"


def test_perfumemarket_search_suggest_parses_shopify_variant_price():
    payload = {
        "resources": {
            "results": {
                "products": [{
                    "title": "French Avenue Liquid Brun Eau de Parfum",
                    "url": "/products/liquid-brun",
                    "variants": [
                        {"price": "31.85", "available": True},
                    ],
                }]
            }
        }
    }

    rows = perfume_market._parse_search_suggest(payload, "Liquid Brun")

    assert rows == [{
        "store": "PerfumeMarket",
        "name": "French Avenue Liquid Brun Eau de Parfum",
        "price": "31,85 €",
        "url": "https://www.perfumemarket.nl/products/liquid-brun",
    }]


def test_perfumemarket_product_page_uses_jsonld_price_and_rejects_wrong_product():
    html = """<!doctype html><html><head>
      <script type="application/ld+json">
      {
        "@type": "Product",
        "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
        "offers": {
          "@type": "Offer",
          "price": "31.85",
          "priceCurrency": "EUR"
        }
      }
      </script>
    </head><body>
      <h1>French Avenue Liquid Brun Eau de Parfum 100 ml</h1>
    </body></html>"""

    row = perfume_market._parse_product_page(
        html, "Liquid Brun", "https://www.perfumemarket.nl/products/liquid-brun"
    )
    rejected = perfume_market._parse_product_page(
        html, "Sauvage", "https://www.perfumemarket.nl/products/liquid-brun"
    )

    assert row == {
        "store": "PerfumeMarket",
        "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
        "price": "31,85 €",
        "url": "https://www.perfumemarket.nl/products/liquid-brun",
    }
    assert rejected is None
