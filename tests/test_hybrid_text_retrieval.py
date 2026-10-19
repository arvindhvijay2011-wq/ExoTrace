"""Offline tests for score-scale-independent hybrid text retrieval."""

from __future__ import annotations

import pytest

from exotrace.vector.retrieve import (
    DEFAULT_RETRIEVAL_SCOPE,
    DEFAULT_RETRIEVAL_STRATEGY,
    VALID_STRATEGIES,
    reciprocal_rank_fusion,
    tokenize,
)


def test_rrf_rewards_documents_ranked_by_both_channels() -> None:
    fused = reciprocal_rank_fusion(
        [
            ["shared", "lexical-only", "lexical-third"],
            ["shared", "dense-only", "dense-third"],
        ]
    )
    scores = dict(fused)

    assert fused[0][0] == "shared"
    assert scores["shared"] == pytest.approx((1 / 61) + (1 / 61))
    assert scores["lexical-only"] == pytest.approx(1 / 62)


def test_rrf_deduplicates_an_id_inside_each_ranking() -> None:
    fused = reciprocal_rank_fusion([["a", "a", "b"], ["b", "a"]], rrf_k=10)
    scores = dict(fused)

    assert scores["a"] == pytest.approx(1 / 11 + 1 / 12)
    assert scores["b"] == pytest.approx(1 / 13 + 1 / 11)


def test_rrf_rejects_nonpositive_k() -> None:
    with pytest.raises(ValueError, match="rrf_k"):
        reciprocal_rank_fusion([["a"]], rrf_k=0)


def test_tokenizer_retains_basic_scientific_terms_and_ids() -> None:
    tokens = tokenize("TRAPPIST-1 e: orbital-period, Earth-radius, H/alpha")
    assert "trappist-1" in tokens
    assert "earth-radius" in tokens
    assert "orbital-period" in tokens


def test_tokenizer_preserves_nasa_schema_field_identifier() -> None:
    tokens = tokenize("What does pl_orbeccen describe?")
    assert "pl_orbeccen" in tokens


def test_dense_is_documented_default_based_on_current_benchmark() -> None:
    assert DEFAULT_RETRIEVAL_STRATEGY == "dense"
    assert VALID_STRATEGIES == {"bm25", "dense", "rrf"}


def test_default_scope_is_explicit_and_does_not_inspect_query_text() -> None:
    assert DEFAULT_RETRIEVAL_SCOPE == "references"
