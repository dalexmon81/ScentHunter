"""Catalog identity result aggregation, independent of application globals."""


def aggregate_identity_results(
    offers,
    *,
    is_non_fragrance_offer,
    is_concentration_mismatch_offer,
    public_offer,
):
    """Group publishable matched offers and preserve unresolved offers."""
    groups = {}
    unresolved = []

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        status = str(offer.get("_match_status") or "unresolved").lower()

        if status == "matched" and offer.get("catalog_id"):
            if is_non_fragrance_offer(offer) or is_concentration_mismatch_offer(offer):
                continue

            catalog_id = str(offer.get("catalog_id")).strip()
            if catalog_id not in groups:
                brand = offer.get("canonical_brand") or offer.get("brand")
                groups[catalog_id] = {
                    "catalog_id": catalog_id,
                    "brand": brand,
                    "canonical_brand": brand,
                    "name": offer.get("canonical_name") or offer.get("name"),
                    "family": offer.get("family"),
                    "variant": offer.get("variant"),
                    "canonical_name": offer.get("canonical_name"),
                    "image": offer.get("canonical_image") or "",
                    "offers": [],
                }

            groups[catalog_id]["offers"].append(public_offer(offer))

        elif status == "unresolved":
            unresolved.append(public_offer(offer))

    result = list(groups.values())
    for group in result:
        group["offers"] = sorted(
            group["offers"],
            key=lambda item: (
                item.get("price_num")
                if item.get("price_num") is not None
                else 999999.0
            ),
        )

    result.sort(
        key=lambda group: (group.get("canonical_name") or "").lower()
    )
    return result, unresolved
