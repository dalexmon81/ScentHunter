"""Build query identity scope through the configured product matcher."""

def identity_scope(query, product_matcher, logger=print):
    if product_matcher is None:
        return []
    try:
        method = getattr(PRODUCT_MATCHER, "build_identity_scope", None)
        if callable(method):
            return method(str(query or "").strip())
        method = getattr(PRODUCT_MATCHER, "build_query_scope", None)
        if callable(method):
            return method(str(query or "").strip())
        return []
    except Exception as exc:
        logger(
            f'PRODUCT_IDENTITY_SCOPE_ERROR: {type(exc).__name__}: {exc}',
            flush=True,
        )
        return []
