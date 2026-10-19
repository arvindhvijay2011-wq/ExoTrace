"""Offline tests for the first two ExoTrace specialist agents."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from exotrace.agents.assembly import build_initial_specialist_layer
from exotrace.agents.catalogue_data import CatalogueDataAgent
from exotrace.agents.contracts import AgentStatus, AgentTask
from exotrace.agents.literature_definition import LiteratureDefinitionAgent
from exotrace.tools.catalogue_lookup import CatalogueLookupConfig, CatalogueRecordLookupTool
from exotrace.tools.literature_search import LiteratureSearchTool
from exotrace.tools.registry import ToolRegistry


class FakeRetriever:
    """Minimal retriever for specialist tests; does not load a real FAISS model."""

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []
        self.calls: list[dict[str, Any]] = []
        self.corpus_sha256 = "corpus-test-sha"
        self.corpus_manifest = {"snapshot_id": "PSCompPars::test"}

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        scope: str = "references",
        strategy: str = "dense",
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {"query": query, "top_k": top_k, "scope": scope, "strategy": strategy}
        )
        return self.documents[:top_k]


def make_reference_document() -> dict[str, Any]:
    """Return one definition-style document with provenance metadata."""
    return {
        "doc_id": "reference:definition:field_a",
        "doc_type": "official_nasa_parameter_definition",
        "title": "Field A definition",
        "text": "Source-derived description of field A.",
        "metadata": {"source_url": "https://example.test/field-a"},
        "retrieval": {"selected_rank": 1, "strategy": "dense"},
    }


def write_catalogue(tmp_path: Path) -> CatalogueLookupConfig:
    """Create a checksum-matched validated CSV and its report for agent integration tests."""
    csv_path = tmp_path / "planets_validated.csv"
    rows = [
        {"pl_name": "Planet A", "hostname": "Star A", "pl_orbper": "12.5"},
        {"pl_name": "Planet B", "hostname": "Star B", "pl_orbper": "25.0"},
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("pl_name", "hostname", "pl_orbper"))
        writer.writeheader()
        writer.writerows(rows)
    report_path = tmp_path / "validation_report.json"
    report_path.write_text(
        json.dumps(
            {
                "passed": True,
                "row_count": len(rows),
                "raw_sha256": hashlib.sha256(b"raw source").hexdigest(),
                "processed_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return CatalogueLookupConfig(catalogue_path=csv_path, validation_report_path=report_path)


def test_literature_agent_returns_source_excerpts_and_validates_evidence_ids() -> None:
    retriever = FakeRetriever([make_reference_document()])
    tool_registry = ToolRegistry((LiteratureSearchTool(retriever),))
    agent = LiteratureDefinitionAgent()
    task = AgentTask(
        task_id="literature-task-1",
        question="What does field A describe?",
        objective="Retrieve source text relevant to field A.",
        required_capabilities=("parameter.definition",),
        allowed_tool_ids=("literature.search",),
        context={"top_k": 3},
    )

    executor = tool_registry.executor_for(agent.descriptor, task)
    result = agent.run(task, tools=executor)

    result.validate_for(task, agent.descriptor)
    assert result.status is AgentStatus.SUCCEEDED
    assert result.agent_id == "literature_definition"
    assert len(result.findings) == 1
    assert result.findings[0].statement == "Source-derived description of field A."
    assert result.findings[0].evidence_ids == (result.evidence[0].evidence_id,)
    assert result.evidence[0].source_uri == "https://example.test/field-a"
    assert result.tool_ids_used == ("literature.search",)
    assert retriever.calls[0]["scope"] == "references"


def test_literature_agent_does_not_call_tool_for_unsupported_capability() -> None:
    retriever = FakeRetriever([make_reference_document()])
    tool_registry = ToolRegistry((LiteratureSearchTool(retriever),))
    agent = LiteratureDefinitionAgent()
    task = AgentTask(
        task_id="wrong-capability-task",
        question="Compare catalogue measurements.",
        objective="Perform quantitative analysis.",
        required_capabilities=("quantitative.analysis",),
        allowed_tool_ids=("literature.search",),
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "unsupported_capability"
    assert result.tool_ids_used == ()
    assert retriever.calls == []


def test_literature_agent_requires_task_allowlist_for_its_tool() -> None:
    retriever = FakeRetriever([make_reference_document()])
    tool_registry = ToolRegistry((LiteratureSearchTool(retriever),))
    agent = LiteratureDefinitionAgent()
    task = AgentTask(
        task_id="denied-literature-task",
        question="Find the definition.",
        objective="Retrieve a source passage.",
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "task_tool_not_granted"
    assert result.tool_ids_used == ()
    assert retriever.calls == []


def test_literature_agent_reports_insufficient_evidence_for_empty_retrieval() -> None:
    tool_registry = ToolRegistry((LiteratureSearchTool(FakeRetriever([])),))
    agent = LiteratureDefinitionAgent()
    task = AgentTask(
        task_id="empty-literature-task",
        question="A query with no matches",
        objective="Retrieve reference passages.",
        allowed_tool_ids=("literature.search",),
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.INSUFFICIENT_EVIDENCE
    assert result.findings == ()
    assert result.evidence == ()
    assert result.gaps


def test_catalogue_agent_returns_exact_raw_values_and_provenance(tmp_path: Path) -> None:
    config = write_catalogue(tmp_path)
    catalogue_tool = CatalogueRecordLookupTool(config=config)
    tool_registry = ToolRegistry((catalogue_tool,))
    agent = CatalogueDataAgent()
    task = AgentTask(
        task_id="catalogue-task-1",
        question="Retrieve the orbital period for Planet A.",
        objective="Return raw catalogue fields for the specified planet.",
        required_capabilities=("catalogue.raw_values",),
        allowed_tool_ids=("catalogue.lookup",),
        context={"filters": {"pl_name": "Planet A"}, "fields": ["pl_name", "pl_orbper"]},
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    result.validate_for(task, agent.descriptor)
    assert result.status is AgentStatus.SUCCEEDED
    assert result.agent_id == "catalogue_data"
    assert len(result.findings) == 1
    assert json.loads(result.evidence[0].excerpt) == {
        "pl_name": "Planet A",
        "pl_orbper": "12.5",
    }
    assert result.evidence[0].snapshot_id == catalogue_tool.snapshot_id
    assert result.findings[0].evidence_ids == (result.evidence[0].evidence_id,)
    assert result.tool_ids_used == ("catalogue.lookup",)


def test_catalogue_agent_accepts_compact_field_value_filter_clauses(tmp_path: Path) -> None:
    catalogue_tool = CatalogueRecordLookupTool(config=write_catalogue(tmp_path))
    tool_registry = ToolRegistry((catalogue_tool,))
    agent = CatalogueDataAgent()
    task = AgentTask(
        task_id="compact-catalogue-task",
        question="Retrieve the orbital period for Planet A.",
        objective="Return raw catalogue fields for the specified planet.",
        required_capabilities=("catalogue.raw_values",),
        allowed_tool_ids=("catalogue.lookup",),
        context={
            "filters": [{"field": "pl_name", "value": "Planet A"}],
            "fields": ["pl_name", "pl_orbper"],
            "match_mode": "exact",
            "limit": 1,
        },
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.SUCCEEDED
    assert json.loads(result.evidence[0].excerpt)["pl_orbper"] == "12.5"


def test_catalogue_agent_rejects_literal_null_filter_placeholder(tmp_path: Path) -> None:
    catalogue_tool = CatalogueRecordLookupTool(config=write_catalogue(tmp_path))
    tool_registry = ToolRegistry((catalogue_tool,))
    agent = CatalogueDataAgent()
    task = AgentTask(
        task_id="bad-placeholder-task",
        question="Retrieve a catalogue record.",
        objective="Return raw catalogue fields.",
        required_capabilities=("catalogue.raw_values",),
        allowed_tool_ids=("catalogue.lookup",),
        context={
            "filters": [
                {"field": "pl_name", "value": "Planet A"},
                {"field": "cb_flag", "value": "null"},
            ],
            "fields": ["pl_name"],
        },
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "invalid_structured_filters"
    assert "placeholder" in str(result.error_message)
    assert result.tool_ids_used == ()


def test_catalogue_agent_requires_structured_filters_and_does_not_parse_question(
    tmp_path: Path,
) -> None:
    catalogue_tool = CatalogueRecordLookupTool(config=write_catalogue(tmp_path))
    tool_registry = ToolRegistry((catalogue_tool,))
    agent = CatalogueDataAgent()
    task = AgentTask(
        task_id="unstructured-catalogue-task",
        question="Look up Planet A's orbital period.",
        objective="Retrieve a catalogue measurement.",
        allowed_tool_ids=("catalogue.lookup",),
        context={"fields": ["pl_name", "pl_orbper"]},
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "missing_structured_filters"
    assert result.tool_ids_used == ()


def test_catalogue_agent_requires_explicit_fields(tmp_path: Path) -> None:
    catalogue_tool = CatalogueRecordLookupTool(config=write_catalogue(tmp_path))
    tool_registry = ToolRegistry((catalogue_tool,))
    agent = CatalogueDataAgent()
    task = AgentTask(
        task_id="missing-fields-task",
        question="Retrieve Planet A.",
        objective="Retrieve specified catalogue fields.",
        allowed_tool_ids=("catalogue.lookup",),
        context={"filters": {"pl_name": "Planet A"}},
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "missing_requested_fields"
    assert result.tool_ids_used == ()


def test_catalogue_agent_reports_no_matches_as_insufficient_evidence(tmp_path: Path) -> None:
    catalogue_tool = CatalogueRecordLookupTool(config=write_catalogue(tmp_path))
    tool_registry = ToolRegistry((catalogue_tool,))
    agent = CatalogueDataAgent()
    task = AgentTask(
        task_id="catalogue-no-match-task",
        question="Look up an unknown object.",
        objective="Retrieve requested source fields.",
        allowed_tool_ids=("catalogue.lookup",),
        context={"filters": {"pl_name": "No such planet"}, "fields": ["pl_name"]},
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.INSUFFICIENT_EVIDENCE
    assert result.findings == ()
    assert result.gaps



def test_specialist_public_exports_load_without_package_import_cycles() -> None:
    from exotrace.agents import (
        CatalogueDataAgent as PublicCatalogueDataAgent,
        LiteratureDefinitionAgent as PublicLiteratureDefinitionAgent,
        build_initial_specialist_layer as public_assembly,
    )
    from exotrace.tools import (
        CatalogueRecordLookupTool as PublicCatalogueRecordLookupTool,
        LiteratureSearchTool as PublicLiteratureSearchTool,
    )

    assert PublicCatalogueDataAgent is CatalogueDataAgent
    assert PublicLiteratureDefinitionAgent is LiteratureDefinitionAgent
    assert callable(public_assembly)
    assert PublicCatalogueRecordLookupTool is CatalogueRecordLookupTool
    assert PublicLiteratureSearchTool is LiteratureSearchTool

def test_initial_specialist_assembly_registers_only_the_two_bounded_agents(
    tmp_path: Path,
) -> None:
    agents, tools = build_initial_specialist_layer(
        FakeRetriever([make_reference_document()]),
        catalogue_config=write_catalogue(tmp_path),
    )

    agent_descriptors = {descriptor.agent_id: descriptor for descriptor in agents.descriptors()}
    tool_descriptors = {descriptor.tool_id: descriptor for descriptor in tools.descriptors()}

    assert set(agent_descriptors) == {"literature_definition", "catalogue_data"}
    assert set(tool_descriptors) == {"literature.search", "catalogue.lookup"}
    assert agent_descriptors["literature_definition"].allowed_tool_ids == ("literature.search",)
    assert agent_descriptors["catalogue_data"].allowed_tool_ids == ("catalogue.lookup",)
