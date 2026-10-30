"""Evidence-backed variant learning from repeated live retailer observations.

This module learns only missing variants of an already-existing canonical
product. It never creates product identities, merges products, infers sizes,
or promotes a one-retailer guess. Two independent retailer domains must agree
on the exact product identity, explicit size, and concentration.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


_UNSAFE_PACKAGING = re.compile(
    r"\b(?:refill\w*|nachfullung|nachfullpackung|recharge|tester|testeur|"
    r"sample|probe|decant|gift\s*set|coffret|bundle|discovery\s*set)\b",
    re.I,
)
_CONCENTRATION_PATTERNS = (
    (re.compile(r"\b(?:extrait de parfum|parfum intense|extrait)\b", re.I), "extrait de parfum"),
    (re.compile(r"\b(?:eau de parfum intense|edp intense)\b", re.I), "eau de parfum intense"),
    (re.compile(r"\b(?:eau de toilette intense|edt intense)\b", re.I), "eau de toilette intense"),
    (re.compile(r"\b(?:eau de parfum|edp)\b", re.I), "eau de parfum"),
    (re.compile(r"\b(?:eau de toilette|edt)\b", re.I), "eau de toilette"),
    (re.compile(r"\b(?:eau de cologne|edc)\b", re.I), "eau de cologne"),
    (re.compile(r"\bparfum\b", re.I), "parfum"),
)


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _concentration(value: Any) -> str | None:
    text = str(value or "")
    for pattern, canonical in _CONCENTRATION_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def _identity_name(value: Any, brand: Any) -> str:
    text = _norm(value)
    brand_norm = _norm(brand)
    if brand_norm and text.startswith(brand_norm + " "):
        text = text[len(brand_norm):]
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|dl|l|oz|fl oz)\b",
        " ",
        text,
    )
    for pattern, _ in _CONCENTRATION_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(r"\bfor her\b", "women", text)
    text = re.sub(r"\bfor him\b", "men", text)
    text = re.sub(
        r"\b(?:for men|for women|men|man|women|woman|herren|damen|unisex|male|female)\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def _unsupported_storefront_locale(url: Any) -> bool:
    """Detect Deloox Spanish routes accidentally attached to another market host."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return True
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    first_segment = next((part.casefold() for part in parsed.path.split("/") if part), "")
    return host.startswith("deloox.") and first_segment == "producto" and host != "deloox.es"


def _retailer_domain(url: Any) -> str | None:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.casefold().removeprefix("www.")
    return host or None


def _url_identity_name(url: Any, brand: Any) -> str | None:
    """Extract the product identity from the final URL slug, ignoring only generic packaging words.

    A retailer title can be normalized too aggressively (for example, a broad
    "Sauvage Eau de Parfum" label can point at the distinct "Sauvage Eau Forte"
    page). The URL slug is an independent identity signal; meaningful flanker
    words must remain and must agree with the title.
    """
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return None
    slug = parsed.path.rsplit("/", 1)[-1]
    slug = re.sub(r"\.(?:html?|aspx?|php)$", "", slug, flags=re.I)
    slug = _norm(slug)
    if not slug:
        return None
    # Product IDs, brand repeats and retailer SEO suffixes are not perfume
    # identity. Remove them while retaining meaningful flankers such as
    # "Eau Forte", "Elixir", "Malibu", or "Limited Edition".
    slug = re.sub(r"\b\d+\b", " ", slug)
    brand_tokens = set(_norm(brand).split())
    tokens = [token for token in slug.split() if token not in brand_tokens]
    slug = " ".join(tokens)
    slug = re.sub(
        r"\b(?:by|copy|perfume|perfumes|spray|vapo|vaporizer|vaporiser|"
        r"vaporisateur|vaporizador|atomizer|aerosol)\b",
        " ",
        slug,
    )
    return _identity_name(slug, brand)


def _explicit_size(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        size = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not size.is_integer() or size <= 0 or size > 5000:
        return None
    return int(size)


def _stable_variant_id(product_id: str, size_ml: int, concentration: str) -> str:
    key = f"{product_id}|{size_ml}|{concentration}|bottle"
    return "VAR-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]




def _canonical_product_name(value: Any, brand: Any) -> str:
    text = str(value or "").strip()
    brand_text = str(brand or "").strip()
    if brand_text and _norm(text).startswith(_norm(brand_text) + " "):
        text = text[len(brand_text):].strip()
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|dl|l|oz|fl oz)\b",
        " ",
        text,
        flags=re.I,
    )
    for pattern, _ in _CONCENTRATION_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(
        r"\b(?:eau de parfum|eau de toilette|eau de cologne|edp|edt|edc|"
        r"for men|for women|men|man|women|woman|herren|damen|unisex)\b",
        " ",
        text,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", text).strip(" -|")


def _stable_product_id(brand: str, name: str, concentration: str) -> str:
    key = f"{_norm(brand)}|{_norm(name)}|{concentration}"
    return "SH-AUTO-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def learn_variants(
    catalog: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
    *,
    min_retailers: int = 2,
) -> dict[str, Any]:
    """Return a copied catalog plus auditable additions; never mutate input.

    Observations should contain product_id, name, brand, size_ml, retailer, and
    product_url. Shadow report rows may provide candidate_product_ids instead
    of product_id; those are accepted only when exactly one candidate exists.
    """
    if min_retailers < 2:
        raise ValueError("min_retailers must be at least 2")
    if not isinstance(catalog, Mapping):
        raise ValueError("catalog root must be an object")
    products = catalog.get("products")
    variants = catalog.get("variants")
    if not isinstance(products, list) or not isinstance(variants, list):
        raise ValueError("catalog must contain products and variants arrays")

    observation_rows = [row for row in observations if isinstance(row, Mapping)]
    learned_products: list[dict[str, Any]] = []
    rejected: dict[str, int] = defaultdict(int)
    product_by_id = {
        str(row.get("product_id")): row
        for row in products
        if isinstance(row, Mapping) and row.get("product_id")
    }

    # A previously unseen product may be proposed only when at least two
    # independent retailer domains agree on the same brand/name/concentration
    # and on at least one explicit size. Ambiguous or incomplete catalog matches
    # block creation instead of silently making a duplicate canonical product.
    new_product_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in observation_rows:
        product_id = str(item.get("product_id") or "").strip()
        candidates = item.get("candidate_product_ids")
        if product_id:
            continue
        name = str(item.get("name") or item.get("raw_name") or "").strip()
        brand = str(item.get("brand") or "").strip()

        # A single matcher candidate is not proof that the retailer offer is
        # that product: broad family records can attract distinct flankers.
        # Only consider an unmatched offer for new-product proposal when every
        # supplied candidate exists in the catalog and none matches its exact
        # brand/name identity. Matching candidates continue through variant
        # learning; missing/invalid candidate records remain conservative.
        if isinstance(candidates, list) and candidates:
            if not brand or not name:
                continue
            candidate_rows = []
            invalid_candidate = False
            for candidate in candidates:
                candidate_id = str(candidate or "").strip()
                candidate_row = product_by_id.get(candidate_id)
                if isinstance(candidate_row, Mapping):
                    candidate_rows.append(candidate_row)
                elif candidate_id.startswith("SH-FAMILY-"):
                    # Family IDs emitted by the matcher are grouping hints,
                    # not canonical catalog products. They must not block a
                    # separately evidenced product proposal just because no
                    # canonical row exists for the family placeholder.
                    continue
                else:
                    invalid_candidate = True
                    break
            if invalid_candidate:
                continue
            exact_candidate = any(
                _norm(row.get("brand_name")) == _norm(brand)
                and _identity_name(row.get("canonical_name") or row.get("name"), brand)
                    == _identity_name(name, brand)
                for row in candidate_rows
            )
            if exact_candidate:
                continue

        size = _explicit_size(item.get("size_ml"))
        url = str(item.get("product_url") or item.get("url") or "")
        domain = _retailer_domain(url)
        if _unsupported_storefront_locale(url):
            rejected["storefront_locale_conflict"] += 1
            continue
        title_concentration = _concentration(name)
        url_concentration = _concentration(url.replace("-", " ").replace("_", " "))
        concentration = title_concentration or url_concentration
        canonical_name = _canonical_product_name(name, brand)
        url_identity = _url_identity_name(url, brand)
        if url_concentration and title_concentration and url_concentration != title_concentration:
            rejected["url_concentration_conflict"] += 1
            continue
        if url_identity and set(url_identity.split()) != set(_identity_name(name, brand).split()):
            rejected["url_identity_conflict"] += 1
            continue
        if (
            not name or not brand or not size or not domain or not concentration
            or not canonical_name
            or _UNSAFE_PACKAGING.search(name)
            or _UNSAFE_PACKAGING.search(url)
        ):
            continue
        key = (_norm(brand), _norm(canonical_name), concentration)
        new_product_groups[key].append({
            **dict(item),
            "brand": brand,
            "name": name,
            "size_ml": size,
            "domain": domain,
            "concentration": concentration,
            "canonical_name": canonical_name,
        })

    rewritten_observations = [dict(item) for item in observation_rows]
    for (brand_key, name_key, concentration), rows in new_product_groups.items():
        by_size: dict[int, set[str]] = defaultdict(set)
        all_domains: set[str] = set()
        for row in rows:
            by_size[int(row["size_ml"])].add(str(row["domain"]))
            all_domains.add(str(row["domain"]))
        if len(all_domains) < min_retailers or not any(
            len(domains) >= min_retailers for domains in by_size.values()
        ):
            rejected["new_product_insufficient_independent_evidence"] += 1
            continue

        exemplar = rows[0]
        brand = str(exemplar["brand"])
        canonical_name = str(exemplar["canonical_name"])
        same_name = [
            row for row in product_by_id.values()
            if _norm(row.get("brand_name")) == brand_key
            and _identity_name(row.get("canonical_name") or row.get("name"), brand)
                == _identity_name(canonical_name, brand)
        ]
        exact_concentration = [
            row for row in same_name
            if _concentration(row.get("concentration")) == concentration
        ]
        if len(exact_concentration) == 1:
            target_id = str(exact_concentration[0].get("product_id"))
        elif exact_concentration or same_name:
            rejected["new_product_identity_ambiguous"] += 1
            continue
        else:
            target_id = _stable_product_id(brand, canonical_name, concentration)
            if target_id in product_by_id:
                rejected["new_product_id_collision"] += 1
                continue
            new_product = {
                "product_id": target_id,
                "brand_name": brand,
                "canonical_name": canonical_name,
                "concentration": concentration,
                "aliases": list(dict.fromkeys(str(row["name"]) for row in rows)),
            }
            product_by_id[target_id] = new_product
            learned_products.append(new_product)

        # Rewrite only unambiguous observations in this exact evidence group.
        for row in rows:
            for observation in rewritten_observations:
                if (
                    not observation.get("product_id")
                    and str(observation.get("product_url") or observation.get("url") or "")
                        == str(row.get("product_url") or row.get("url") or "")
                    and str(observation.get("name") or observation.get("raw_name") or "")
                        == str(row.get("name") or "")
                ):
                    observation["product_id"] = target_id

    existing = {
        (str(row.get("product_id")), _explicit_size(row.get("size_ml")))
        for row in variants
        if isinstance(row, Mapping)
    }

    evidence: dict[tuple[str, int, str], dict[str, Any]] = {}
    for item in rewritten_observations:
        if not isinstance(item, Mapping):
            rejected["invalid_observation"] += 1
            continue
        product_id = str(item.get("product_id") or "").strip()
        candidates = item.get("candidate_product_ids")
        if not product_id and isinstance(candidates, list) and len(candidates) == 1:
            product_id = str(candidates[0] or "").strip()
        if not product_id or product_id not in product_by_id:
            rejected["no_unique_existing_product"] += 1
            continue

        product = product_by_id[product_id]
        size = _explicit_size(item.get("size_ml"))
        retailer = str(item.get("retailer") or "").strip()
        url = str(item.get("product_url") or item.get("url") or "").strip()
        domain = _retailer_domain(url)
        if _unsupported_storefront_locale(url):
            rejected["storefront_locale_conflict"] += 1
            continue
        brand = str(item.get("brand") or "").strip()
        name = str(item.get("name") or item.get("raw_name") or "").strip()
        product_brand = str(product.get("brand_name") or "").strip()
        product_name = str(product.get("canonical_name") or product.get("name") or "").strip()
        title_concentration = _concentration(name)
        url_concentration = _concentration(url.replace("-", " ").replace("_", " "))
        offer_concentration = title_concentration or url_concentration
        canonical_concentration = _concentration(product.get("concentration"))

        if not size or not retailer or not domain or not name or not product_brand or not product_name:
            rejected["missing_required_evidence"] += 1
            continue
        if brand and _norm(brand) != _norm(product_brand):
            rejected["brand_conflict"] += 1
            continue
        if _identity_name(name, brand or product_brand) != _identity_name(product_name, product_brand):
            rejected["product_name_conflict"] += 1
            continue
        url_identity = _url_identity_name(url, brand or product_brand)
        if (
            not offer_concentration
            or (
                canonical_concentration is not None
                and offer_concentration != canonical_concentration
            )
            or (
                title_concentration is not None
                and url_concentration is not None
                and title_concentration != url_concentration
            )
        ):
            rejected["concentration_unverified_or_conflict"] += 1
            continue
        if url_identity and set(url_identity.split()) != set(_identity_name(name, brand or product_brand).split()):
            rejected["url_identity_conflict"] += 1
            continue
        url_concentration = _concentration(url)
        if url_concentration and url_concentration != offer_concentration:
            rejected["url_concentration_conflict"] += 1
            continue
        if _UNSAFE_PACKAGING.search(name) or _UNSAFE_PACKAGING.search(url):
            rejected["special_packaging_requires_review"] += 1
            continue
        if (product_id, size) in existing:
            rejected["variant_already_exists"] += 1
            continue

        key = (product_id, size, offer_concentration)
        bucket = evidence.setdefault(key, {
            "product_id": product_id,
            "size_ml": size,
            "concentration": offer_concentration,
            "retailers": {},
        })
        bucket["retailers"].setdefault(domain, {
            "retailer": retailer,
            "product_url": url,
            "name": name,
        })

    updated = json.loads(json.dumps(catalog))
    updated["products"].extend(learned_products)
    added = []
    for key, bucket in sorted(evidence.items()):
        retailer_evidence = list(bucket["retailers"].values())
        if len(retailer_evidence) < min_retailers:
            rejected["insufficient_independent_retailers"] += 1
            continue
        product_id, size, concentration = key
        variant_id = _stable_variant_id(product_id, size, concentration)
        if any(
            isinstance(row, Mapping) and str(row.get("variant_id") or "") == variant_id
            for row in updated["variants"]
        ):
            rejected["variant_id_collision"] += 1
            continue
        names = list(dict.fromkeys(str(row["name"]).strip() for row in retailer_evidence if row.get("name")))
        variant = {
            "variant_id": variant_id,
            "product_id": product_id,
            "size_ml": size,
            "aliases": names,
        }
        updated["variants"].append(variant)
        added.append({
            **variant,
            "concentration": concentration,
            "independent_retailer_count": len(retailer_evidence),
            "evidence": retailer_evidence,
        })

    return {
        "catalog": updated,
        "report": {
            "schema_version": 1,
            "mode": "evidence-backed-variant-learning",
            "catalog_mutated": False,
            "input_catalog_mutated": False,
            "automatic_product_creation": "proposal_only",
            "products_added": len(learned_products),
            "added_products": learned_products,
            "product_merges": 0,
            "minimum_independent_retailers": min_retailers,
            "variants_added": len(added),
            "added_variants": added,
            "rejected_observation_counts": dict(sorted(rejected.items())),
        },
    }


def learn_from_shadow_report(catalog: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    """Consume unresolved examples from a production shadow report."""
    observations = []
    queries = report.get("queries", []) if isinstance(report.get("queries"), list) else []
    for query in queries:
        if not isinstance(query, Mapping):
            continue
        retailers = query.get("retailers", []) if isinstance(query.get("retailers"), list) else []
        for retailer_report in retailers:
            if not isinstance(retailer_report, Mapping):
                continue
            retailer = str(retailer_report.get("retailer") or "").strip()
            unresolved_examples = retailer_report.get("unresolved_examples", [])
            ambiguous_examples = retailer_report.get("ambiguous_examples", [])
            examples = []
            if isinstance(unresolved_examples, list):
                examples.extend(unresolved_examples)
            if isinstance(ambiguous_examples, list):
                examples.extend(ambiguous_examples)
            for example in examples:
                if not isinstance(example, Mapping):
                    continue
                observations.append({**example, "retailer": retailer})
    return learn_variants(catalog, observations)
