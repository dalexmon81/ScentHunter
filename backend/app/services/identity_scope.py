"""Build query identity scope through the configured product matcher."""

def identity_scope(query, product_matcher, logger=print):
    if product_matcher is None:
        return []
    try:
        method = getattr(product_matcher, "build_identity_scope", None)
        if callable(method):
            return method(str(query or "").strip())
        method = getattr(product_matcher, "build_query_scope", None)
        if callable(method):
            return method(str(query or "").strip())
        return []
    except Exception as exc:
        try:
            logger(f'PRODUCT_IDENTITY_SCOPE_ERROR: {type(exc).__name__}: {exc}')
        except Exception:
            # Diagnostics must never turn a safe empty identity scope into a
            # failed search response.
            pass
        return []
