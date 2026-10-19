"""Tests for source-level evaluation of both NASA chunks and definition documents."""

from exotrace.vector.evaluate_retrieval import first_relevant_rank, source_slug


def test_source_slug_recognizes_reference_chunk() -> None:
    assert source_slug("reference:archive_parameter_columns:chunk:0012") == "archive_parameter_columns"


def test_source_slug_recognizes_source_derived_parameter_definition() -> None:
    assert source_slug("reference:archive_parameter_columns:chunk:field_pl_orbeccen") == "archive_parameter_columns"


def test_parameter_definition_counts_as_relevant_for_its_source_page() -> None:
    ranked = [
        "reference:detection_methods:chunk:0001",
        "reference:archive_parameter_columns:chunk:field_pl_orbeccen",
    ]
    assert first_relevant_rank(ranked, {"archive_parameter_columns"}) == 2
