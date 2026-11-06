"""Bounded catalog search-term expansion helpers."""
import re


def catalog_search_terms(query, product_matcher=None):
    """Return bounded persistent-catalog search terms.

    Keep the original query first, then include a wider set of family-aware
    canonical names and aliases. Broad queries such as "Hawas" must be able to
    retrieve distinct variants whose retailer titles omit the family word
    (for example, "Kobra For Him"). ProductMatcher remains solely responsible
    for deciding final product identity.
    """
    text = str(query or "").strip()
    if not text:
        return []

    terms = [text]
    if product_matcher is None:
        return terms

    try:
        method = getattr(product_matcher, "catalog_search_terms", None)
        if not callable(method):
            return terms
        expanded = method(text)
        if not isinstance(expanded, (list, tuple)):
            return terms

        def tokens(value):
            return {
                token for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
                if len(token) >= 3
            }

        query_tokens = tokens(text)
        if not query_tokens:
            return terms

        candidates = []
        seen = {text.casefold()}
        for item in expanded:
            candidate = str(item or "").strip()
            key = candidate.casefold()
            if not candidate or key in seen:
                continue
            candidate_tokens = tokens(candidate)
            seen.add(key)
            overlap = candidate_tokens & query_tokens
            # A single-token family query (for example "Hawas") may have
            # legitimate catalog aliases whose retailer titles contain none
            # of the family token. Keep those aliases in the matcher's order;
            # ProductMatcher remains responsible for rejecting unrelated
            # products. Multi-token queries still require lexical overlap so
            # expansion does not flood the search with unrelated candidates.
            if not overlap and len(query_tokens) > 1:
                continue
            candidates.append((candidate, overlap))

        token_frequency = {
            token: sum(1 for _, overlap in candidates if token in overlap)
            for token in query_tokens
        }
        candidates.sort(
            key=lambda item: (
                sum(1.0 / token_frequency[token] for token in item[1]),
                len(item[1]),
                -len(item[0]),
            ),
            reverse=True,
        )

        # Single-token family queries (for example "Hawas") need the full
        # registry vocabulary because valid variant titles may omit the family
        # token. Multi-token queries already constrain candidates lexically;
        # running dozens of near-duplicate aliases adds repeated SQLite FTS
        # work without materially improving recall. Keep the original query
        # plus a ranked, bounded set for these queries.
        # Broad one-token family searches must cover the registered variant vocabulary.
        # Eight terms truncated families with more aliases (e.g. Hawas), hiding valid
        # variants even when the catalog already contains them. catalog_engine bounds
        # the per-store candidate pool, so allow the full bounded registry expansion.
        # Multi-token family searches also need room for separately
        # registered variants (e.g. Liquid Brun Limited Edition). Four terms
        # truncated these related aliases before catalog lookup could see them.
        max_terms = 32 if len(query_tokens) <= 1 else 4
        token_order = sorted(
            query_tokens,
            key=lambda token: (token_frequency.get(token, 0), token),
        )
        selected = set()
        for token in token_order:
            for candidate, overlap in candidates:
                if token in overlap and candidate.casefold() not in selected:
                    terms.append(candidate)
                    selected.add(candidate.casefold())
                    break
            if len(terms) >= max_terms:
                return terms[:max_terms]

        for candidate, _ in candidates:
            if len(terms) >= max_terms:
                break
            if candidate.casefold() not in selected:
                terms.append(candidate)
                selected.add(candidate.casefold())
        return terms[:max_terms]
    except Exception as exc:
        print(
            f"CATALOG_SEARCH_TERM_EXPANSION_ERROR: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return terms

