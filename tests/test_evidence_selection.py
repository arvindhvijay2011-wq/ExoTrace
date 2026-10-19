"""Tests for conservative, provenance-driven answer evidence selection."""

from __future__ import annotations

from typing import Any

import pytest

from exotrace.answering.evidence_selection import select_answer_evidence


SOURCE_URL = "https://example.test/source"


def primary_document(
    field: str = "pl_orbeccen",
    title: str = "Eccentricity (pl_orbeccen)",
) -> dict[str, Any]:
    """Build a synthetic direct source-row definition document."""
    return {
        "doc_id": f"definition:{field}",
        "doc_type": "official_nasa_parameter_definition",
        "title": title,
        "text": "Description copied from a direct source-table row.",
        "metadata": {
            "parameter_field": field,
            "definition_extraction": "official_table_row",
            "source_url": SOURCE_URL,
        },
    }


def derived_document(
    *,
    field: str = "pl_orbeccenlim",
    parent_field: str = "pl_orbeccen",
    kind: str = "derived_from_official_limit_association",
    title: str = "Eccentricity limit column (pl_orbeccenlim)",
) -> dict[str, Any]:
    """Build a synthetic mechanically derived association document."""
    return {
        "doc_id": f"derived:{field}",
        "doc_type": "official_nasa_parameter_definition",
        "title": title,
        "text": (
            "Role inferred from official source association. "
            "Parent parameter description copied from its source row."
        ),
        "metadata": {
            "parameter_field": field,
            "related_parameter_field": parent_field,
            "definition_extraction": kind,
            "source_url": SOURCE_URL,
        },
    }


def test_general_parent_question_filters_redundant_limit_association() -> None:
    primary = primary_document()
    derived = derived_document()
    other = {
        "doc_id": "reference:general",
        "title": "NASA Exoplanet Archive overview",
        "text": "An overview of the archive.",
        "metadata": {"source_url": SOURCE_URL},
    }

    selected = select_answer_evidence(
        "What does planetary orbital eccentricity describe?",
        [derived, primary, other],
    )

    assert [item["doc_id"] for item in selected] == [
        "definition:pl_orbeccen",
        "reference:general",
    ]


def test_explicit_associated_field_identifier_keeps_derived_record() -> None:
    primary = primary_document()
    derived = derived_document()

    selected = select_answer_evidence(
        "What does the pl_orbeccenlim field indicate?",
        [derived, primary],
    )

    assert [item["doc_id"] for item in selected] == [
        "derived:pl_orbeccenlim",
        "definition:pl_orbeccen",
    ]


def test_query_about_association_role_keeps_derived_record() -> None:
    primary = primary_document()
    derived = derived_document()

    selected = select_answer_evidence(
        "What is the purpose of the limit column?",
        [derived, primary],
    )

    assert [item["doc_id"] for item in selected] == [
        "derived:pl_orbeccenlim",
        "definition:pl_orbeccen",
    ]


def test_query_about_uncertainty_keeps_uncertainty_association() -> None:
    primary = primary_document()
    derived = derived_document(
        field="pl_orbeccenerr1",
        kind="derived_from_official_uncertainty_association",
        title="Eccentricity positive upper uncertainty (pl_orbeccenerr1)",
    )

    selected = select_answer_evidence(
        "What is the upper uncertainty field for eccentricity?",
        [derived, primary],
    )

    assert [item["doc_id"] for item in selected] == [
        "derived:pl_orbeccenerr1",
        "definition:pl_orbeccen",
    ]


def test_unrequested_derived_document_is_filtered_without_parent_document() -> None:
    derived = derived_document()

    selected = select_answer_evidence(
        "Explain eccentricity in general terms.",
        [derived],
    )

    assert selected == []


def test_other_document_order_is_preserved_and_maximum_is_applied_after_filtering() -> None:
    primary = primary_document()
    derived = derived_document()
    reference_a = {"doc_id": "ref:a", "text": "A", "title": "A"}
    reference_b = {"doc_id": "ref:b", "text": "B", "title": "B"}

    selected = select_answer_evidence(
        "What does eccentricity describe?",
        [derived, reference_a, primary, reference_b],
        max_documents=2,
    )

    assert [item["doc_id"] for item in selected] == [
        "ref:a",
        "definition:pl_orbeccen",
    ]


def test_empty_query_and_nonpositive_document_limit_are_rejected() -> None:
    with pytest.raises(ValueError, match="Query cannot be empty"):
        select_answer_evidence("  ", [])

    with pytest.raises(ValueError, match="at least 1"):
        select_answer_evidence("query", [], max_documents=0)


def test_input_documents_are_not_mutated() -> None:
    document = primary_document()
    original = {key: value for key, value in document.items()}

    selected = select_answer_evidence("What is eccentricity?", [document])

    assert selected == [original]
    assert document == original


def test_answer_question_integrates_filter_and_oversamples_candidates() -> None:
    from exotrace.answering.ask import answer_question

    primary = primary_document()
    derived = derived_document()
    retrieved_docs = [
        derived,
        primary,
        *[
            {
                "doc_id": f"reference:{index}",
                "title": f"Reference {index}",
                "text": f"Reference text {index}.",
                "metadata": {"source_url": SOURCE_URL},
            }
            for index in range(20)
        ],
    ]

    class StubRetriever:
        """Return preset documents and record requested retrieval arguments."""

        corpus_sha256 = "test-corpus-hash"

        def __init__(self) -> None:
            self.requested_top_k = 0

        def search(
            self,
            query: str,
            *,
            top_k: int,
            scope: str,
            strategy: str,
        ) -> list[dict[str, Any]]:
            assert query == "What does eccentricity describe?"
            assert scope == "references"
            assert strategy == "dense"
            self.requested_top_k = top_k
            return retrieved_docs[:top_k]

    class StubAnswerer:
        """Capture evidence documents passed to answer generation."""

        def __init__(self) -> None:
            self.received_documents: list[dict[str, Any]] = []

        def answer(
            self,
            query: str,
            documents: list[dict[str, Any]],
            *,
            retrieval_strategy: str,
            retrieval_scope: str,
            corpus_sha256: str | None,
        ) -> list[dict[str, Any]]:
            assert query == "What does eccentricity describe?"
            assert retrieval_strategy == "dense"
            assert retrieval_scope == "references"
            assert corpus_sha256 == "test-corpus-hash"
            self.received_documents = documents
            return documents

    retriever = StubRetriever()
    answerer = StubAnswerer()
    selected = answer_question(
        "What does eccentricity describe?",
        retriever=retriever,  # type: ignore[arg-type]
        answerer=answerer,  # type: ignore[arg-type]
        top_k=6,
        scope="references",
        strategy="dense",
    )

    assert retriever.requested_top_k == 18
    assert len(selected) == 6
    assert len(answerer.received_documents) == 6
    assert "derived:pl_orbeccenlim" not in {
        item["doc_id"] for item in answerer.received_documents
    }
    assert answerer.received_documents[0]["doc_id"] == "definition:pl_orbeccen"
