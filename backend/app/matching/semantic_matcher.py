"""Optional semantic candidate scoring; no provider means no semantic match."""
from __future__ import annotations

import math
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    """Adapter implemented by an explicitly configured embedding service."""

    def embed(self, text: str) -> Sequence[float]:
        """Return one finite, non-empty embedding vector for text."""


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Return cosine similarity, rejecting malformed or degenerate vectors."""
    if not left or not right or len(left) != len(right):
        return None
    try:
        a = [float(value) for value in left]
        b = [float(value) for value in right]
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in (*a, *b)):
        return None
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a == 0 or norm_b == 0:
        return None
    score = sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)
    return score if math.isfinite(score) else None


def semantic_candidate_score(
    provider: EmbeddingProvider | None, source_text: str, candidate_text: str,
) -> float | None:
    """Score a pair only when a real provider is supplied and returns valid vectors."""
    if provider is None:
        return None
    if not source_text.strip() or not candidate_text.strip():
        return None
    try:
        return cosine_similarity(provider.embed(source_text), provider.embed(candidate_text))
    except Exception:
        # Provider/network/model errors must fall back to review, never auto-match.
        return None
