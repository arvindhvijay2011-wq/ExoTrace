"""Regression test: source-derived NASA definitions must be searchable in references scope."""

from exotrace.vector.retrieve import (
    PARAMETER_DEFINITION_DOC_TYPE,
    REFERENCE_DOC_TYPE,
    allowed_doc_types,
)


def test_references_scope_includes_original_nasa_chunks_and_parameter_definitions() -> None:
    assert allowed_doc_types("references") == {
        REFERENCE_DOC_TYPE,
        PARAMETER_DEFINITION_DOC_TYPE,
    }


def test_parameter_definition_type_is_source_derived_nasa_definition_type() -> None:
    assert PARAMETER_DEFINITION_DOC_TYPE == "official_nasa_parameter_definition"


def test_profile_scope_remains_profiles_only() -> None:
    assert allowed_doc_types("profiles") == {"planet_profile"}


def test_all_scope_remains_unrestricted() -> None:
    assert allowed_doc_types("all") is None
