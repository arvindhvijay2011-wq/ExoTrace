"""Tests for ExoTrace query scope selection and document-type filters."""

import pytest

from exotrace.vector.retrieve import DEFAULT_RETRIEVAL_SCOPE, allowed_doc_types


@pytest.mark.parametrize("scope", ["all", "references", "profiles"])
def test_allowed_doc_types_accepts_supported_scope(scope: str) -> None:
    result = allowed_doc_types(scope)
    if scope == "all":
        assert result is None
    elif scope == "references":
        assert result == {"official_nasa_reference_chunk", "official_nasa_parameter_definition"}
    else:
        assert result == {"planet_profile"}


def test_allowed_doc_types_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError, match="Unsupported retrieval scope"):
        allowed_doc_types("unknown")



def test_default_scope_is_references_and_requires_explicit_override_for_profiles() -> None:
    assert DEFAULT_RETRIEVAL_SCOPE == "references"
    assert allowed_doc_types("profiles") == {"planet_profile"}
