"""Select retrieved evidence conservatively before scientific answer generation.

This module uses source-provenance metadata already present in ExoTrace's corpus. It
filters mechanically derived uncertainty/limit association documents unless the query
appears to target that associated field or role. It does not contain planet facts,
scientific definitions, known field IDs, or question-specific routing rules.

The filter is intentionally conservative: mechanically generated association records
repeat a parent parameter's description, so they can look semantically relevant while
not being the primary definition of the queried parameter. If a query explicitly asks
about that associated field or role, the record is retained.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*", re.IGNORECASE)
_GENERIC_EXTRACTION_TOKENS = {"derived", "from", "official", "association"}


def _tokens(value: str) -> set[str]:
    """Return lowercase tokens while preserving underscore-based field identifiers."""
    return {token.casefold() for token in _TOKEN_PATTERN.findall(value)}


def _metadata(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return document metadata only when it is mapping-like."""
    value = document.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _extraction_kind(document: Mapping[str, Any]) -> str:
    """Return the corpus provenance label for the document's extraction method."""
    value = _metadata(document).get("definition_extraction")
    return value.strip().casefold() if isinstance(value, str) else ""


def _is_derived_association(document: Mapping[str, Any]) -> bool:
    """Identify mechanically derived table-association records by their provenance."""
    kind = _extraction_kind(document)
    return kind.startswith("derived_from_official_") and kind.endswith("_association")


def _field(document: Mapping[str, Any], key: str) -> str | None:
    """Read a field identifier from metadata without assuming it exists."""
    value = _metadata(document).get(key)
    if isinstance(value, str) and value.strip():
        return value.strip().casefold()
    return None


def _field_is_named_in_query(query_tokens: set[str], document: Mapping[str, Any]) -> bool:
    """Return true when the user explicitly names this document's field identifier."""
    own_field = _field(document, "parameter_field")
    return own_field is not None and own_field in query_tokens


def _association_role_tokens(document: Mapping[str, Any]) -> set[str]:
    """Extract role terms from source provenance rather than from scientific facts."""
    kind_tokens = _tokens(_extraction_kind(document))
    return kind_tokens - _GENERIC_EXTRACTION_TOKENS


def _primary_documents_by_field(
    documents: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """Index non-derived parameter documents by their own field identifier."""
    result: dict[str, list[Mapping[str, Any]]] = {}
    for document in documents:
        field = _field(document, "parameter_field")
        if not field or _is_derived_association(document):
            continue
        result.setdefault(field, []).append(document)
    return result


def _query_targets_derived_document(
    query_tokens: set[str],
    document: Mapping[str, Any],
    primary_documents_by_field: Mapping[str, list[Mapping[str, Any]]],
) -> bool:
    """Determine whether a query explicitly asks about an associated field or role.

    An exact field identifier is the strongest signal. Otherwise, provenance-derived
    role tokens (for example, ``limit`` or ``uncertainty``) must occur in the query.
    When the primary parent record is also retrieved, additional title terms unique to
    the derived record can indicate direct relevance to that association.
    """
    if _field_is_named_in_query(query_tokens, document):
        return True

    if query_tokens.intersection(_association_role_tokens(document)):
        return True

    parent_field = _field(document, "related_parameter_field")
    if not parent_field:
        return False

    parent_documents = primary_documents_by_field.get(parent_field, [])
    if not parent_documents:
        # Without the primary row, the relationship label alone is insufficient to
        # treat a derived association as a direct definition of the parent parameter.
        return False

    title = document.get("title")
    if not isinstance(title, str):
        return False
    derived_title_tokens = _tokens(title)

    parent_title_tokens: set[str] = set()
    for parent in parent_documents:
        parent_title = parent.get("title")
        if isinstance(parent_title, str):
            parent_title_tokens.update(_tokens(parent_title))

    own_field = _field(document, "parameter_field")
    related_field = _field(document, "related_parameter_field")
    if own_field:
        derived_title_tokens.discard(own_field)
    if related_field:
        derived_title_tokens.discard(related_field)

    association_specific_tokens = derived_title_tokens - parent_title_tokens
    return bool(query_tokens.intersection(association_specific_tokens))


def select_answer_evidence(
    query: str,
    documents: Sequence[Mapping[str, Any]],
    *,
    max_documents: int | None = None,
) -> list[dict[str, Any]]:
    """Filter redundant derived records while preserving retrieval order otherwise.

    Parameters
    ----------
    query:
        The user's original natural-language question.
    documents:
        Documents returned by the selected retriever strategy, already in rank order.
    max_documents:
        Optional upper bound for the evidence count after filtering. No new documents
        are retrieved and no scores or original document metadata are modified.

    Returns
    -------
    list[dict[str, Any]]
        Shallow copies of retained documents in their original retrieval order.
    """
    if not query.strip():
        raise ValueError("Query cannot be empty.")
    if max_documents is not None and max_documents < 1:
        raise ValueError("max_documents must be at least 1 when provided.")

    query_tokens = _tokens(query)
    primary_by_field = _primary_documents_by_field(documents)
    retained: list[dict[str, Any]] = []

    for document in documents:
        if not isinstance(document, Mapping):
            continue
        if _is_derived_association(document) and not _query_targets_derived_document(
            query_tokens,
            document,
            primary_by_field,
        ):
            continue

        retained.append(dict(document))
        if max_documents is not None and len(retained) >= max_documents:
            break

    return retained
