"""Filtering rules for excluding non-fragrance retailer products."""
import re

_NON_FRAGRANCE_TITLE_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:gift\s*set|set\s*regalo|coffret|cofre|estuche|"
    r"discovery\s*set|sample(?:s)?|sample\s*set|mystery\s*box|beauty\s*box|"
    r"gift\s*box|bundle|pack\s*regalo|duo|trio|kit|case|set|"
    r"decant(?:s)?|tester(?:s)?|testeur(?:s)?|probe(?:s)?|proben|proef(?:je|jes)?|pröbchen|échantillon(?:s)?|muestra(?:s)?)(?:[^a-z0-9]|$)",
    re.I,
)

_NON_FRAGRANCE_CATEGORY_RE = re.compile(
    r"(?:cosmetic|cosmetics|make[- ]?up|maquill|skincare|skin\s*care|"
    r"hair\s*care|shampoo|conditioner|body\s*care|bath|shower|"
    r"cream|crema|lotion|serum|mascara|lipstick|candle|vela|home|"
    r"accessor|accessori|jewell|joyer|watch|reloj|bag|bolso|"
    r"toiletr|wallet|cartera|brush|pennello|sponge|esponja|"
    r"deodorant|desodorante|aftershave|rasage|soap|jabon|"
    r"cleanser|limpiador(?:a|es)?|nettoyant(?:s)?|face\\s*wash|"
    r"facial\\s*cleanser|toner|tonique|gesichtswasser|shaving|"
    r"gel\\s*de\\s*afeitado|gel\\s*de\\s*rasage)(?:[^a-z0-9]|$)",
    re.I,
)

# "Home" is meaningful in a category field, but can appear in a valid
# fragrance title (for example, "Home fragrance perfume"). Do not use that
# broad category token against product titles.
_NON_FRAGRANCE_TITLE_CATEGORY_RE = re.compile(
    _NON_FRAGRANCE_CATEGORY_RE.pattern.replace("|home|", "|"),
    re.I,
)


def is_non_fragrance_offer(item):
    """Reject generic non-perfume commercial items before matching/publication.

    This is intentionally category-based, never product-specific. Bundles,
    gift sets, mystery boxes and clearly non-fragrance categories are not
    individual perfume offers, so they must not enter either the matcher or
    the unresolved-offers UI.
    """
    if not isinstance(item, dict):
        return True

    for key in ("is_fragrance", "is_perfume"):
        if key in item and item.get(key) is False:
            return True

    category_values = []
    for key in (
        "product_type", "productType", "category", "category_name",
        "categoryName", "department", "type", "product_category",
        "productCategory",
    ):
        value = item.get(key)
        if value not in (None, ""):
            category_values.append(str(value))

    category_text = " ".join(category_values)
    if category_text and _NON_FRAGRANCE_CATEGORY_RE.search(category_text):
        return True

    title_parts = []
    for key in ("name", "title", "raw_name", "_raw_name", "canonical_name"):
        value = item.get(key)
        if value not in (None, ""):
            title_parts.append(str(value))
    title_text = " ".join(title_parts)

    # A retailer title can be mislabeled, so inspect URL slugs too, but
    # use a narrow URL-only vocabulary: broad category words such as "home"
    # can occur in unrelated URL fragments and suppress valid perfume offers.
    url_parts = []
    for key in ("url", "product_url", "link", "product_page", "source_url", "_raw_url", "retailer_url"):
        value = item.get(key)
        if value not in (None, ""):
            url_parts.append(str(value))
    url_text = " ".join(url_parts).lower()
    non_fragrance_url_re = re.compile(
        r"(?:^|[/_?&=-])(?:cleanser|limpiador(?:a|es)?|nettoyant(?:s)?|"
        r"face[-_ ]?wash|facial[-_ ]?cleanser|gesichtswasser|"
        r"toner|tonique|shampoo|conditioner|moisturizer|moisturiser|"
        r"carbon[-_ ]negro[-_ ]y[-_ ]cactus)(?:$|[/_?&=.-])",
        re.I,
    )

    return bool(
        _NON_FRAGRANCE_TITLE_RE.search(title_text)
        or _NON_FRAGRANCE_TITLE_CATEGORY_RE.search(title_text)
        or non_fragrance_url_re.search(url_text)
    )

