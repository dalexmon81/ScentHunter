def test_notino_non_perfume_page_cannot_fall_back_to_generic_parser(monkeypatch, tmp_path):
    import catalog_engine

    url = "https://www.notino.fr/dior/sauvage-dedorant-stick-pour-hommesans-alcool/"
    body = (
        "<html><head><title>DIOR Sauvage Déodorant stick sans alcool</title></head>"
        "<body><h1>DIOR Sauvage Déodorant stick sans alcool pour homme</h1>"
        "<script type='application/ld+json'>"
        '{"@type":"Product","name":"Sauvage Eau de Parfum","offers":{"price":"35.50"}}'
        "</script></body></html>"
    ).encode("utf-8")

    monkeypatch.setattr(catalog_engine, "DB_PATH", tmp_path / "notino-identity.sqlite3")
    monkeypatch.setattr(catalog_engine, "_SCHEMA_READY", False)
    monkeypatch.setattr(
        catalog_engine,
        "http_get",
        lambda requested_url, timeout=None: (200, requested_url, body),
    )
    # The authoritative Notino parser rejects the deodorant destination.
    monkeypatch.setattr(catalog_engine, "_secondary_store_parser", lambda *args, **kwargs: None)

    generic_calls = []

    def misleading_generic_parser(store, final_url, html_data):
        generic_calls.append((store, final_url))
        return {
            "name": "Sauvage Eau de Parfum",
            "brand": "Dior",
            "price_num": 35.50,
            "currency": "EUR",
            "availability": "in_stock",
        }

    monkeypatch.setattr(catalog_engine, "parse_product", misleading_generic_parser)

    result = catalog_engine.refresh_url("notino", url)

    assert result is None
    assert generic_calls == []

    conn = catalog_engine.db()
    try:
        row = conn.execute(
            "SELECT price, fetch_status FROM store_products WHERE store=? AND url=?",
            ("notino", url),
        ).fetchone()
        assert row is not None
        assert row["price"] is None
        assert "product_parser_not_found" in str(row["fetch_status"])
    finally:
        conn.close()
