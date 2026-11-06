"""Offline parser-contract regressions for the Easycosmetic German storefront.

These tests use saved synthetic HTML only: they make no retailer requests and
exercise the adapter's own selected-variant and offer extraction behavior.
"""
from scrapers.easycosmetic import scraper as easycosmetic


PRODUCT_URL = "https://www.easycosmetic.de/acqua-di-gio-profondo-eau-de-parfum"


def _product_html():
    return """<!doctype html>
    <html><head>
      <script type="application/ld+json">
      [
        {
          "@type": "Product",
          "name": "Acqua di Gio Profondo Eau de Parfum 75 ml",
          "url": "https://www.easycosmetic.de/acqua-di-gio-profondo-eau-de-parfum?variant=750",
          "brand": {"@type": "Brand", "name": "Giorgio Armani"},
          "image": "https://cdn2.easycosmetic.de/acqua-di-gio-profondo-75ml.png",
          "offers": {"@type": "Offer", "price": "79.90",
                     "priceCurrency": "EUR",
                     "availability": "https://schema.org/InStock"}
        },
        {
          "@type": "Product",
          "name": "Acqua di Gio Profondo Eau de Parfum 100 ml",
          "url": "https://www.easycosmetic.de/acqua-di-gio-profondo-eau-de-parfum?variant=1000",
          "brand": {"@type": "Brand", "name": "Giorgio Armani"},
          "image": "https://cdn2.easycosmetic.de/acqua-di-gio-profondo-100ml.png",
          "offers": {"@type": "Offer", "price": "99.90",
                     "priceCurrency": "EUR",
                     "availability": "https://schema.org/OutOfStock"}
        }
      ]
      </script>
    </head>
    <body>
      <main class="product-detail">
        <h1>Acqua di Gio Profondo Eau de Parfum</h1>
        <div class="product-price"><span>89,95 €</span></div>
        <div>Ausverkauft</div>
        <div class="content-left">
          <img class="product" alt="Acqua di Gio Profondo Eau de Parfum 100 ml"
               src="https://cdn2.easycosmetic.de/acqua-di-gio-profondo-100ml.png">
        </div>
      </main>
    </body></html>"""


def test_easycosmetic_variant_url_selects_matching_jsonld_offer_and_size():
    row = easycosmetic.extract_product_page(
        None, PRODUCT_URL + "?variant=1000", html=_product_html()
    )

    assert row is not None
    assert row["shop"] == "Easycosmetic"
    assert row["brand"] == "Giorgio Armani"
    assert row["currency"] == "EUR"
    assert row["size_ml"] == 100
    # The visible product-detail price overrides potentially cached JSON-LD.
    assert row["price_num"] == 89.95
    assert row["available"] is False
    assert row["availability"] == "Out of stock"
    assert row["url"].endswith("?variant=1000")


def test_easycosmetic_variant_with_no_matching_jsonld_does_not_borrow_other_size():
    html = _product_html().replace('variant=1000', 'variant=9999')
    row = easycosmetic.extract_product_page(
        None, PRODUCT_URL + "?variant=9999", html=html
    )

    assert row is not None
    assert row["size_ml"] == 100
    # No JSON-LD object for variant 9999: don't borrow the 75 ml or 100 ml
    # offer. The page-scoped visible price remains independently usable.
    assert row["price_num"] == 89.95
    assert row["brand"] == ""


def test_easycosmetic_does_not_invent_eur_when_selected_offer_omits_currency():
    html = _product_html().replace(',\n                     "priceCurrency": "EUR"', '')
    row = easycosmetic.extract_product_page(
        None, PRODUCT_URL + "?variant=1000", html=html
    )

    assert row is not None
    assert row["price_num"] == 89.95
    assert row["currency"] is None


def test_easycosmetic_rejects_malformed_currency_code():
    html = _product_html().replace('"priceCurrency": "EUR"', '"priceCurrency": "EURO"')
    row = easycosmetic.extract_product_page(
        None, PRODUCT_URL + "?variant=1000", html=html
    )

    assert row is not None
    assert row["currency"] is None
