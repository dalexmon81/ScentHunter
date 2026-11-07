"""Central ProductMatcher offer identity resolution service."""

def _safe_log(logger, message):
    try:
        logger(message)
    except Exception:
        # Logging must not turn a fail-closed identity result into a failed search.
        pass


def resolve_offer_identity(result, query, product_matcher, store_labels, normalize_store, logger=print):
    """Resolve one raw retailer offer through the central ProductMatcher.

    The canonical matcher contract is ``match(offer, query)``.  Older
    ``build_query_scope`` / ``match_offer`` calls were a different contract and
    caused valid retailer rows to remain unresolved even though the catalog
    contained the product.
    """
    if not isinstance(result, dict):
        return None

    output = dict(result)

    if product_matcher is None:
        output.update({
            "_match_status": "unresolved",
            "catalog_id": None,
            "canonical_name": None,
        })
        return output

    try:
        match_method = getattr(product_matcher, "match", None)
        if not callable(match_method):
            raise RuntimeError("ProductMatcher non espone match(offer, query)")

        # IMPORTANT: some retailer APIs put their own vendor/store name in
        # nested source metadata. ProductMatcher is allowed to fall back to
        # source.brand/source_brand, so even after the public ``brand`` field
        # is cleaned that retailer label can still become a false brand
        # constraint.
        #
        # For the matcher input only, build a clean identity payload. The
        # public/output object is left untouched. When the top-level brand is
        # the retailer label, remove the entire nested source identity and
        # keep the already-normalized product name as the authoritative name.
        matcher_offer = dict(output)
        matcher_brand = str(matcher_offer.get("brand") or "").strip()
        matcher_store_label = "".join(
            str(store_labels.get(
                normalize_store(matcher_offer.get("store") or matcher_offer.get("shop"), ""),
                normalize_store(matcher_offer.get("store") or matcher_offer.get("shop"), ""),
            ) or "")
            .lower()
            .replace("-", " ")
            .split()
        )
        matcher_brand_normalized = "".join(
            matcher_brand.lower().replace("-", " ").split()
        )
        if matcher_brand_normalized == matcher_store_label or (
            not matcher_brand_normalized
            and str(output.get("_raw_brand") or "").strip()
            and "".join(str(output.get("_raw_brand") or "").lower().replace("-", " ").split()) == matcher_store_label
        ):
            matcher_offer["brand"] = ""
            matcher_offer.pop("manufacturer", None)
            source = matcher_offer.get("source")
            if isinstance(source, dict):
                clean_source = dict(source)
                for key in ("source_brand", "brand", "manufacturer"):
                    clean_source.pop(key, None)
                matcher_offer["source"] = clean_source
            elif source is not None:
                matcher_offer.pop("source", None)

        match = match_method(matcher_offer, str(query or "").strip())
    except Exception as exc:
        _safe_log(logger, f"product_matcher_MATCH_ERROR: {type(exc).__name__}: {exc}")
        output.update({
            "_match_status": "unresolved",
            "catalog_id": None,
            "canonical_name": None,
            "_match_error": f"{type(exc).__name__}: {exc}",
        })
        return output

    if not isinstance(match, dict):
        # ``None`` can mean an ordinary unresolved identity or an intentional
        # non-publish rejection. Ask the same central matcher for the explicit
        # rejection reason instead of duplicating its rules in main.py.
        rejection_method = getattr(product_matcher, "rejection_reason", None)
        rejection_reason = None
        if callable(rejection_method):
            try:
                rejection_reason = rejection_method(matcher_offer)
            except Exception as exc:
                _safe_log(logger, f"product_matcher_REJECTION_STATUS_ERROR: {type(exc).__name__}: {exc}")

        if rejection_reason:
            output.update({
                "_match_status": "rejected",
                "_reject_reason": rejection_reason,
                "catalog_id": None,
                "canonical_name": None,
            })
            return output

        # A known family query has a closed identity scope: ProductMatcher is
        # authoritative for the registered variants of that family. If an
        # offer reaches this point without resolving, it is not a member of
        # the requested family and must not leak into `unresolved_offers`.
        # This is generic family-scope handling; it contains no product or
        # retailer-specific exceptions.
        family_resolver = getattr(product_matcher, "_family_for_query", None)
        if callable(family_resolver):
            try:
                requested_family = family_resolver(str(query or "").strip())
            except Exception as exc:
                requested_family = None
                _safe_log(logger, f"product_matcher_FAMILY_SCOPE_ERROR: {type(exc).__name__}: {exc}")
            if requested_family is not None:
                output.update({
                    "_match_status": "rejected",
                    "_reject_reason": "outside_query_family",
                    "catalog_id": None,
                    "canonical_name": None,
                })
                return output

        output.update({
            "_match_status": "unresolved",
            "catalog_id": None,
            "canonical_name": None,
        })
        return output

    # The central matcher returns the resolved offer directly.  Do not replace
    # the retailer's raw brand/name fields; canonical identity is exposed in
    # its dedicated canonical_* fields.
    output.update(match)
    output["_match_status"] = "matched"

    if not output.get("catalog_id"):
        output["_match_status"] = "unresolved"

    if output.get("canonical_brand") and not output.get("_canonical_brand"):
        output["_canonical_brand"] = output.get("canonical_brand")

    output["match_confidence"] = output.get("confidence")
    return output

from app.services.offer_filtering import (
    _NON_FRAGRANCE_CATEGORY_RE,
    _NON_FRAGRANCE_TITLE_RE,
    is_non_fragrance_offer as _is_non_fragrance_offer,
)
