"""Offline tests for read-only graph investigations and provenance preservation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any


from exotrace.tools.contracts import ToolRequest, ToolStatus
from exotrace.tools.graph_investigation import (
    GraphInvestigationConfig,
    GraphInvestigationTool,
)


class FakeTransaction:
    """Return fixture rows while recording the exact query and bound parameters."""

    def __init__(
        self,
        operation_rows: Mapping[str, list[Mapping[str, Any]]],
        calls: list[dict[str, Any]],
        error: Exception | None = None,
    ) -> None:
        self.operation_rows = operation_rows
        self.calls = calls
        self.error = error

    def run(self, query: str, **parameters: Any) -> Iterable[Mapping[str, Any]]:
        self.calls.append({"query": query, "parameters": dict(parameters)})
        if self.error is not None:
            raise self.error
        operation = next(
            (
                name
                for name in ("planet_context", "host_planets", "planet_records")
                if f"ExoTrace operation: {name}" in query
            ),
            None,
        )
        if operation is None:
            raise AssertionError("Unexpected query was executed.")
        return self.operation_rows.get(operation, [])


class FakeSession:
    """Stand-in for a Neo4j session and managed read transaction."""

    def __init__(self, transaction_factory: Callable[[], FakeTransaction]) -> None:
        self.transaction_factory = transaction_factory

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    def execute_read(
        self, work: Callable[[FakeTransaction], list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        return work(self.transaction_factory())


class FakeDriver:
    """Stand-in driver with no network or database side effects."""

    def __init__(
        self,
        operation_rows: Mapping[str, list[Mapping[str, Any]]],
        *,
        error: Exception | None = None,
    ) -> None:
        self.operation_rows = operation_rows
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.databases: list[str] = []

    def session(self, *, database: str) -> FakeSession:
        self.databases.append(database)
        return FakeSession(
            lambda: FakeTransaction(self.operation_rows, self.calls, self.error)
        )


def planet_context_row() -> dict[str, Any]:
    """Create representative output from the documented imported graph schema."""
    snapshot = "PSCompPars::raw-hash"
    record = "PSCompPars::raw-hash::Kepler-10 b"
    return {
        "entity_name": "Kepler-10 b",
        "entity_found": True,
        "host_stars": [
            {"name": "Kepler-10", "snapshot_id": snapshot, "source_record_id": record}
        ],
        "host_count": 1,
        "discovery_methods": [
            {"name": "Transit", "snapshot_id": snapshot, "source_record_id": record}
        ],
        "discovery_method_count": 1,
        "discovery_facilities": [
            {"name": "Kepler", "snapshot_id": snapshot, "source_record_id": record}
        ],
        "discovery_facility_count": 1,
        "discovery_references": [
            {
                "reference_id": "ref-1",
                "display_name": "Discovery publication",
                "href": "https://example.org/paper",
                "snapshot_id": snapshot,
                "source_record_id": record,
            }
        ],
        "discovery_reference_count": 1,
        "catalogue_records": [
            {
                "record_id": record,
                "snapshot_id": snapshot,
                "source_file": "data/raw/pscomppars.csv",
                "source_row_number": 12,
                "hostname": "Kepler-10",
            }
        ],
        "catalogue_record_count": 1,
    }


def test_graph_tool_descriptor_exposes_only_named_read_only_operations() -> None:
    tool = GraphInvestigationTool(FakeDriver({}))

    assert tool.descriptor.read_only is True
    assert tool.SUPPORTED_OPERATIONS == (
        "planet_context",
        "host_planets",
        "planet_records",
    )
    assert tool.descriptor.input_schema["additionalProperties"] is False
    assert "graph.relationships" in tool.descriptor.capabilities


def test_planet_context_returns_relationship_evidence_with_source_provenance() -> None:
    driver = FakeDriver({"planet_context": [planet_context_row()]})
    tool = GraphInvestigationTool(driver)

    result = tool.execute(
        ToolRequest(
            call_id="graph-call-1",
            tool_id="graph.investigate",
            arguments={"operation": "planet_context", "planet_name": "Kepler-10 b"},
        )
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert len(result.evidence) == 5
    assert {item.metadata["relationship_type"] for item in result.evidence} == {
        "HOSTS",
        "DETECTED_BY",
        "DISCOVERED_AT",
        "HAS_DISCOVERY_REFERENCE",
        "DESCRIBES_PLANET",
    }
    assert all(item.snapshot_id == "PSCompPars::raw-hash" for item in result.evidence)
    assert all(item.record_id == "PSCompPars::raw-hash::Kepler-10 b" for item in result.evidence)
    assert len(result.data["graph_facts"]) == 5
    assert result.data["graph_facts"][0]["evidence_id"] in {
        item.evidence_id for item in result.evidence
    }
    publication_evidence = next(
        item
        for item in result.evidence
        if item.metadata["relationship_type"] == "HAS_DISCOVERY_REFERENCE"
    )
    assert publication_evidence.source_uri == "https://example.org/paper"
    assert driver.databases == ["exotrace"]
    assert len(driver.calls) == 1
    assert "$planet_name" in driver.calls[0]["query"]
    assert driver.calls[0]["parameters"] == {
        "planet_name": "Kepler-10 b",
        "result_limit": 25,
    }


def test_host_planets_operation_preserves_host_edge_snapshot_and_record() -> None:
    snapshot = "PSCompPars::snapshot-1"
    record = "PSCompPars::snapshot-1::Planet A"
    driver = FakeDriver(
        {
            "host_planets": [
                {
                    "entity_name": "Star A",
                    "entity_found": True,
                    "related_planets": [
                        {
                            "planet_name": "Planet A",
                            "snapshot_id": snapshot,
                            "source_record_id": record,
                        }
                    ],
                    "planet_count": 1,
                }
            ]
        }
    )
    result = GraphInvestigationTool(driver).execute(
        ToolRequest(
            call_id="graph-call-2",
            tool_id="graph.investigate",
            arguments={"operation": "host_planets", "host_name": "Star A"},
        )
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert len(result.evidence) == 1
    assert result.evidence[0].snapshot_id == snapshot
    assert result.evidence[0].record_id == record
    assert "Star A" in result.evidence[0].excerpt
    assert "Planet A" in result.evidence[0].excerpt
    assert "$host_name" in driver.calls[0]["query"]


def test_tool_rejects_raw_cypher_and_unknown_arguments_without_database_access() -> None:
    driver = FakeDriver({})
    tool = GraphInvestigationTool(driver)

    raw_query = tool.execute(
        ToolRequest(
            call_id="unsafe-1",
            tool_id="graph.investigate",
            arguments={
                "operation": "planet_context",
                "planet_name": "Planet A",
                "cypher": "MATCH (n) DETACH DELETE n",
            },
        )
    )
    unknown_operation = tool.execute(
        ToolRequest(
            call_id="unsafe-2",
            tool_id="graph.investigate",
            arguments={"operation": "arbitrary_query", "planet_name": "Planet A"},
        )
    )

    assert raw_query.status is ToolStatus.FAILED
    assert raw_query.error_code == "unsupported_arguments"
    assert unknown_operation.status is ToolStatus.FAILED
    assert unknown_operation.error_code == "unsupported_operation"
    assert driver.calls == []


def test_tool_requires_operation_specific_entity_argument() -> None:
    driver = FakeDriver({})
    tool = GraphInvestigationTool(driver)

    missing = tool.execute(
        ToolRequest("missing-entity", "graph.investigate", {"operation": "planet_context"})
    )
    mismatched = tool.execute(
        ToolRequest(
            "mismatched-entity",
            "graph.investigate",
            {"operation": "host_planets", "planet_name": "Planet A"},
        )
    )

    assert missing.status is ToolStatus.FAILED
    assert missing.error_code == "missing_entity_name"
    assert mismatched.status is ToolStatus.FAILED
    assert mismatched.error_code == "missing_entity_name"
    assert driver.calls == []


def test_tool_enforces_configured_result_limit() -> None:
    driver = FakeDriver({})
    tool = GraphInvestigationTool(
        driver,
        config=GraphInvestigationConfig(default_result_limit=3, max_result_limit=4),
    )

    result = tool.execute(
        ToolRequest(
            "too-many",
            "graph.investigate",
            {"operation": "planet_context", "planet_name": "Planet A", "result_limit": 5},
        )
    )

    assert result.status is ToolStatus.FAILED
    assert result.error_code == "invalid_result_limit"
    assert driver.calls == []


def test_tool_marks_results_truncated_when_graph_has_more_items_than_limit() -> None:
    row = planet_context_row()
    row["host_count"] = 4
    driver = FakeDriver({"planet_context": [row]})
    tool = GraphInvestigationTool(
        driver,
        config=GraphInvestigationConfig(default_result_limit=1, max_result_limit=5),
    )

    result = tool.execute(
        ToolRequest(
            "truncated",
            "graph.investigate",
            {"operation": "planet_context", "planet_name": "Kepler-10 b", "result_limit": 1},
        )
    )

    assert result.status is ToolStatus.PARTIAL
    assert result.data["truncated"] is True
    assert "result limit" in (result.message or "")


def test_tool_does_not_create_evidence_for_graph_rows_missing_provenance() -> None:
    row = planet_context_row()
    row["host_stars"] = [{"name": "Star without source metadata"}]
    row["host_count"] = 1
    driver = FakeDriver({"planet_context": [row]})

    result = GraphInvestigationTool(driver).execute(
        ToolRequest(
            "no-provenance",
            "graph.investigate",
            {"operation": "planet_context", "planet_name": "Kepler-10 b"},
        )
    )

    assert result.status is ToolStatus.PARTIAL
    assert result.data["missing_provenance_count"] == 1
    assert all(
        item.metadata["relationship_type"] != "HOSTS"
        for item in result.evidence
    )


def test_tool_reports_missing_entity_without_claiming_relationships() -> None:
    row = {
        "entity_name": None,
        "entity_found": False,
        "host_stars": [], "host_count": 0,
        "discovery_methods": [], "discovery_method_count": 0,
        "discovery_facilities": [], "discovery_facility_count": 0,
        "discovery_references": [], "discovery_reference_count": 0,
        "catalogue_records": [], "catalogue_record_count": 0,
    }
    result = GraphInvestigationTool(FakeDriver({"planet_context": [row]})).execute(
        ToolRequest(
            "not-found",
            "graph.investigate",
            {"operation": "planet_context", "planet_name": "not a planet"},
        )
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.data["entity_found"] is False
    assert result.evidence == ()
    assert result.data["graph_facts"] == []
    assert "No graph entity matched" in (result.message or "")


def test_tool_converts_driver_failures_to_structured_errors() -> None:
    driver = FakeDriver({}, error=RuntimeError("internal connection detail"))
    result = GraphInvestigationTool(driver).execute(
        ToolRequest(
            "driver-failure",
            "graph.investigate",
            {"operation": "planet_context", "planet_name": "Planet A"},
        )
    )

    assert result.status is ToolStatus.FAILED
    assert result.error_code == "graph_read_failed"
    assert "RuntimeError" in (result.message or "")
    assert "internal connection detail" not in (result.message or "")
