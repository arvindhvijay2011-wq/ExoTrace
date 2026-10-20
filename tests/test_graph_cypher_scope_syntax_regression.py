"""Regression tests for modern Neo4j scoped CALL subqueries."""

from __future__ import annotations

import json
import re

import pytest

from exotrace.tools.graph_investigation import (
    GraphInvestigationTool,
    _OPERATION_QUERIES,
)


@pytest.mark.parametrize(
    ("operation", "scope_variable", "expected_call_count"),
    [
        ("planet_context", "planet", 5),
        ("host_planets", "host", 1),
        ("planet_records", "planet", 1),
    ],
)
def test_graph_query_uses_explicit_scope_for_every_subquery(
    operation: str,
    scope_variable: str,
    expected_call_count: int,
) -> None:
    """Every fixed query should import its required outer entity explicitly."""
    query = _OPERATION_QUERIES[operation]
    call_clauses = re.findall(
        r"^\s*CALL(?:\s+\(([^)]*)\))?\s*\{",
        query,
        flags=re.MULTILINE,
    )

    assert len(call_clauses) == expected_call_count
    assert call_clauses == [scope_variable] * expected_call_count
    assert "CALL {" not in query
    assert f"WITH {scope_variable}\n" not in query


def test_graph_queries_remain_fixed_parameterized_read_operations() -> None:
    """Scope-syntax maintenance must not add writes or interpolate entity values."""
    for operation, query in _OPERATION_QUERIES.items():
        assert f"ExoTrace operation: {operation}" in query
        assert "DETACH DELETE" not in query.upper()
        assert "CREATE " not in query.upper()
        assert "MERGE " not in query.upper()
        assert "$result_limit" in query
        if operation == "host_planets":
            assert "$host_name" in query
        else:
            assert "$planet_name" in query


def test_graph_evidence_record_id_matches_its_embedded_provenance() -> None:
    """An evidence item must use one record ID across title, excerpt, and metadata."""
    tool = GraphInvestigationTool(driver=object())  # This helper does not access the driver.
    canonical_record_id = "PSCompPars::snapshot-hash::2MASS J03590986+2009361 b"
    evidence, fact = tool._make_evidence_and_fact(
        operation="planet_context",
        group_name="catalogue_records",
        item={
            "record_id": canonical_record_id,
            "snapshot_id": "PSCompPars::snapshot-hash",
            "source_file": "data/processed/planets_validated.csv",
            "source_row_number": 42,
            "hostname": "2MASS J03590986+2009361",
        },
        contract={
            "relationship_type": "DESCRIBES_PLANET",
            "subject_kind": "catalogue_record",
            "object_kind": "planet",
        },
        entity_name="2MASS J03590986+2009361 b",
        seen_evidence=set(),
    )

    assert evidence is not None
    assert fact is not None
    embedded = json.loads(evidence.excerpt)
    assert evidence.record_id == canonical_record_id
    assert evidence.metadata["source_record_id"] == canonical_record_id
    assert embedded["source_record_id"] == canonical_record_id
    assert canonical_record_id in evidence.title
