"""Read-only status checks for active catalog URLs by store."""


def catalog_indexed_flags(stores, catalog_db, *, on_error=None):
    """Return whether each requested store has at least one active catalog URL.

    The query intentionally avoids joining product and URL tables or calculating
    hydration state. Database failures fail closed for every requested store.
    """
    wanted = [str(store).strip() for store in (stores or []) if str(store).strip()]
    if not wanted or not callable(catalog_db):
        return {store: False for store in wanted}

    conn = None
    try:
        conn = catalog_db()
        flags = {}
        for store in wanted:
            row = conn.execute(
                "SELECT 1 FROM store_urls WHERE store=? AND active=1 LIMIT 1",
                (store,),
            ).fetchone()
            flags[store] = bool(row)
        return flags
    except Exception as exc:
        if callable(on_error):
            on_error(exc)
        return {store: False for store in wanted}
    finally:
        if conn is not None:
            conn.close()
