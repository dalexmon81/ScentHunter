import pytest

from app.matching.semantic_matcher import cosine_similarity, semantic_candidate_score


class FixedProvider:
    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, text):
        return self.vectors[text]


def test_cosine_similarity_scores_identical_vectors():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)


def test_cosine_similarity_rejects_invalid_vectors():
    assert cosine_similarity([1, 0], [1]) is None
    assert cosine_similarity([0, 0], [1, 0]) is None
    assert cosine_similarity([float("nan")], [1]) is None


def test_semantic_score_is_disabled_without_explicit_provider():
    assert semantic_candidate_score(None, "sauvage", "sauvage") is None


def test_semantic_score_fails_closed_when_provider_errors():
    class BrokenProvider:
        def embed(self, text):
            raise RuntimeError("provider unavailable")

    assert semantic_candidate_score(BrokenProvider(), "sauvage", "sauvage") is None


def test_semantic_score_uses_provider_embeddings():
    provider = FixedProvider({"source": [1, 0], "candidate": [0.99, 0.01]})
    assert semantic_candidate_score(provider, "source", "candidate") == pytest.approx(
        0.9999489887
    )
