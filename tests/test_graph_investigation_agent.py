"""Offline tests for the bounded Graph Investigation Agent."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from exotrace.agents import AgentStatus, AgentTask, GraphInvestigationAgent
from exotrace.tools import ToolRegistry
from exotrace.tools.graph_investigation import GraphInvestigationTool


class FakeTransaction:
    """Minimal read-transaction fixture for agent tests."""

    def __init__(
        self, rows: Mapping[str, list[Mapping[str, Any]]], calls: list[dict[str, Any]]
    ) -> None:
        self.rows = rows
        self.calls = calls

    def run(self, query: str, **parameters: Any) -> Iterable[Mapping[str, Any]]:
        self.calls.append({"query": query, "parameters": dict(parameters)})
        operation = next(
            name for name in ("planet_context", "host_planets", "planet_records")
            if f"ExoTrace operation: {name}" in query
        )
        return self.rows.get(operation, [])


class FakeSession:
    """Minimal managed read session fixture."""

    def __init__(self, callback: Callable[[], FakeTransaction]) -> None:
        self.callback = callback

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    def execute_read(
        self, work: Callable[[FakeTransaction], list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        return work(self.callback())


class FakeDriver:
    """Minimal injected driver fixture that never opens a real database connection."""

    def __init__(self, rows: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def session(self, *, database: str) -> FakeSession:
        return FakeSession(lambda: FakeTransaction(self.rows, self.calls))


def planet_context_row() -> dict[str, Any]:
    """Create a small graph response with source provenance."""
    snapshot = "PSCompPars::raw-hash"
    record = "PSCompPars::raw-hash::Kepler-10 b"
    return {
        "entity_name": "Kepler-10 b", "entity_found": True,
        "host_stars": [{"name": "Kepler-10", "snapshot_id": snapshot, "source_record_id": record}],
        "host_count": 1,
        "discovery_methods": [
            {"name": "Transit", "snapshot_id": snapshot, "source_record_id": record}
        ],
        "discovery_method_count": 1,
        "discovery_facilities": [
            {"name": "Kepler", "snapshot_id": snapshot, "source_record_id": record}
        ],
        "discovery_facility_count": 1,
        "discovery_references": [{
            "reference_id": "ref-1", "display_name": "Discovery publication",
            "href": "https://example.org/paper", "snapshot_id": snapshot,
            "source_record_id": record,
        }],
        "discovery_reference_count": 1,
        "catalogue_records": [{
            "record_id": record, "snapshot_id": snapshot,
            "source_file": "data/raw/pscomppars.csv", "source_row_number": 12,
            "hostname": "Kepler-10",
        }],
        "catalogue_record_count": 1,
    }


def make_task(
    *,
    task_id: str = "graph-task-1",
    context: dict[str, Any] | None = None,
    allowed_tool_ids: tuple[str, ...] = ("graph.investigate",),
    required_capabilities: tuple[str, ...] = ("graph.relationships",),
) -> AgentTask:
    """Create a bounded graph task with explicit planner-provided operation arguments."""
    return AgentTask(
        task_id=task_id,
        question="Investigate the host star and discovery context.",
        objective="Return source-backed graph relationship evidence.",
        required_capabilities=required_capabilities,
        allowed_tool_ids=allowed_tool_ids,
        context=context or {"operation": "planet_context", "planet_name": "Kepler-10 b"},
    )


def test_graph_agent_returns_relationship_findings_with_evidence() -> None:
    driver = FakeDriver({"planet_context": [planet_context_row()]})
    graph_tool = GraphInvestigationTool(driver)
    tool_registry = ToolRegistry((graph_tool,))
    agent = GraphInvestigationAgent()
    task = make_task()

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    result.validate_for(task, agent.descriptor)
    assert result.status is AgentStatus.SUCCEEDED
    assert result.agent_id == "graph_investigation"
    assert len(result.findings) == 5
    assert len(result.evidence) == 5
    assert result.tool_ids_used == ("graph.investigate",)
    assert all(len(finding.evidence_ids) == 1 for finding in result.findings)


def test_graph_agent_does_not_parse_operation_from_natural_language_question() -> None:
    driver = FakeDriver({"planet_context": [planet_context_row()]})
    tools = ToolRegistry((GraphInvestigationTool(driver),))
    agent = GraphInvestigationAgent()
    task = AgentTask(
        task_id="no-inferred-op",
        question="Please investigate Kepler-10 b and find its host star.",
        objective="Find graph relationships.",
        required_capabilities=("graph.relationships",),
        allowed_tool_ids=("graph.investigate",),
        context={},
    )

    result = agent.run(task, tools=tools.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "unsupported_operation"
    assert driver.calls == []


def test_graph_agent_refuses_ungranted_task_tool_permission() -> None:
    driver = FakeDriver({"planet_context": [planet_context_row()]})
    registry = ToolRegistry((GraphInvestigationTool(driver),))
    agent = GraphInvestigationAgent()
    task = make_task(allowed_tool_ids=())

    result = agent.run(task, tools=registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "task_tool_not_granted"
    assert result.tool_ids_used == ()
    assert driver.calls == []


def test_graph_agent_refuses_capabilities_outside_its_responsibility() -> None:
    driver = FakeDriver({"planet_context": [planet_context_row()]})
    registry = ToolRegistry((GraphInvestigationTool(driver),))
    agent = GraphInvestigationAgent()
    task = make_task(required_capabilities=("catalogue.numeric_analysis",))

    result = agent.run(task, tools=registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "unsupported_capability"
    assert driver.calls == []


def test_graph_agent_marks_empty_results_as_insufficient_evidence() -> None:
    row = {
        "entity_name": None,
        "entity_found": False,
        "host_stars": [], "host_count": 0,
        "discovery_methods": [], "discovery_method_count": 0,
        "discovery_facilities": [], "discovery_facility_count": 0,
        "discovery_references": [], "discovery_reference_count": 0,
        "catalogue_records": [], "catalogue_record_count": 0,
    }
    driver = FakeDriver({"planet_context": [row]})
    registry = ToolRegistry((GraphInvestigationTool(driver),))
    agent = GraphInvestigationAgent()
    task = make_task()

    result = agent.run(task, tools=registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.INSUFFICIENT_EVIDENCE
    assert result.findings == ()
    assert result.evidence == ()
    assert result.gaps


def test_extended_assembly_registers_three_specialists_with_separate_tools(tmp_path: Path) -> None:
    import csv
    import hashlib
    import json
    from pathlib import Path

    from exotrace.agents import build_specialist_layer
    from exotrace.tools.catalogue_lookup import CatalogueLookupConfig

    csv_path = tmp_path / "planets_validated.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("pl_name", "hostname"))
        writer.writeheader()
        writer.writerow({"pl_name": "Planet A", "hostname": "Star A"})
    checksum = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    report_path = tmp_path / "validation_report.json"
    report_path.write_text(
        json.dumps({"passed": True, "raw_sha256": "snapshot", "processed_sha256": checksum}),
        encoding="utf-8",
    )
    catalogue_config = CatalogueLookupConfig(
        catalogue_path=Path(csv_path),
        validation_report_path=Path(report_path),
    )
    driver = FakeDriver({})

    agents, tools = build_specialist_layer(
        retriever=type("Retriever", (), {"search": lambda self, *args, **kwargs: []})(),
        graph_driver=driver,
        catalogue_config=catalogue_config,
    )

    assert {descriptor.agent_id for descriptor in agents.descriptors()} == {
        "literature_definition",
        "catalogue_data",
        "graph_investigation",
        "quantitative_analysis",
    }
    assert {descriptor.tool_id for descriptor in tools.descriptors()} == {
        "literature.search",
        "catalogue.lookup",
        "graph.investigate",
        "quantitative.calculate",
    }
    assert agents.get("graph_investigation").descriptor.allowed_tool_ids == ("graph.investigate",)
