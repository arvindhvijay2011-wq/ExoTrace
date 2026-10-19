"""Tests for ExoTrace's specialist-agent contracts and registry."""

from __future__ import annotations

from typing import Any

import pytest

from exotrace.agents import (
    AgentDescriptor,
    AgentRegistry,
    AgentRegistryError,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from exotrace.contracts import EvidenceReference, Finding
from exotrace.tools.contracts import ToolExecutor


class FakeAgent:
    """Minimal specialist used to exercise the registry without model calls."""

    def __init__(self, descriptor: AgentDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> AgentDescriptor:
        return self._descriptor

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        del tools
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.descriptor.agent_id,
            status=AgentStatus.SUCCEEDED,
            summary="Completed the delegated task.",
        )


def make_evidence(evidence_id: str = "E1") -> EvidenceReference:
    """Return a valid minimal evidence object."""
    return EvidenceReference(
        evidence_id=evidence_id,
        source_id="nasa-doc-1",
        title="NASA parameter reference",
        excerpt="Source excerpt used by a test.",
        source_uri="https://example.org/reference",
    )


def test_agent_descriptor_is_serializable_and_declares_permissions() -> None:
    descriptor = AgentDescriptor(
        agent_id="literature.specialist",
        name="Literature specialist",
        responsibility="Retrieve source passages and parameter definitions.",
        capabilities=("reference_retrieval", "parameter_definition_lookup"),
        allowed_tool_ids=("vector.search",),
    )

    payload = descriptor.to_dict()

    assert payload["agent_id"] == "literature.specialist"
    assert payload["allowed_tool_ids"] == ["vector.search"]
    assert payload["capabilities"] == [
        "reference_retrieval",
        "parameter_definition_lookup",
    ]


def test_registry_registration_and_capability_matching_are_declarative() -> None:
    literature = FakeAgent(
        AgentDescriptor(
            agent_id="literature",
            name="Literature specialist",
            responsibility="Find sourced definitions.",
            capabilities=("reference_retrieval", "definitions"),
        )
    )
    graph = FakeAgent(
        AgentDescriptor(
            agent_id="graph",
            name="Graph specialist",
            responsibility="Investigate graph relationships.",
            capabilities=("graph_traversal", "entity_relationships"),
        )
    )
    registry = AgentRegistry((literature, graph))

    candidates = registry.candidates_for(("graph_traversal",))

    assert [agent.descriptor.agent_id for agent in candidates] == ["graph"]
    assert registry.get("literature") is literature
    assert {item.agent_id for item in registry.descriptors()} == {"literature", "graph"}


def test_registry_rejects_duplicate_agent_ids() -> None:
    descriptor = AgentDescriptor(
        agent_id="same-id",
        name="Agent",
        responsibility="Perform a bounded task.",
        capabilities=("example",),
    )

    with pytest.raises(AgentRegistryError, match="already registered"):
        AgentRegistry((FakeAgent(descriptor), FakeAgent(descriptor)))


def test_task_requires_explicit_allowed_tools_and_is_json_safe() -> None:
    task = AgentTask(
        task_id="task-1",
        question="What does the parameter mean?",
        objective="Retrieve the authoritative definition.",
        required_capabilities=("definitions",),
        allowed_tool_ids=("vector.search",),
        input_evidence=(make_evidence(),),
        context={"retrieval_scope": "references"},
    )

    payload = task.to_dict()

    assert payload["allowed_tool_ids"] == ["vector.search"]
    assert payload["input_evidence"][0]["evidence_id"] == "E1"
    assert payload["context"]["retrieval_scope"] == "references"


def test_result_rejects_findings_that_cite_unknown_evidence() -> None:
    task = AgentTask(
        task_id="task-1",
        question="What does the parameter mean?",
        objective="Retrieve the authoritative definition.",
        input_evidence=(make_evidence("E1"),),
    )
    descriptor = AgentDescriptor(
        agent_id="literature",
        name="Literature specialist",
        responsibility="Find sourced definitions.",
        capabilities=("definitions",),
    )
    result = AgentResult(
        task_id="task-1",
        agent_id="literature",
        status=AgentStatus.SUCCEEDED,
        summary="Found a definition.",
        findings=(
            Finding(
                finding_id="F1",
                statement="The parameter describes an orbital property.",
                finding_type="scientific_claim",
                evidence_ids=("E404",),
            ),
        ),
    )

    with pytest.raises(ValueError, match="not available to this task"):
        result.validate_for(task, descriptor)


def test_result_accepts_input_and_new_evidence_references() -> None:
    input_evidence = make_evidence("E1")
    new_evidence = make_evidence("E2")
    task = AgentTask(
        task_id="task-1",
        question="What does the parameter mean?",
        objective="Find and summarize authoritative evidence.",
        input_evidence=(input_evidence,),
        allowed_tool_ids=("vector.search",),
    )
    descriptor = AgentDescriptor(
        agent_id="literature",
        name="Literature specialist",
        responsibility="Find sourced definitions.",
        capabilities=("definitions",),
        allowed_tool_ids=("vector.search",),
    )
    result = AgentResult(
        task_id="task-1",
        agent_id="literature",
        status=AgentStatus.SUCCEEDED,
        summary="Found related source evidence.",
        findings=(
            Finding(
                finding_id="F1",
                statement="The source describes the parameter.",
                finding_type="scientific_claim",
                evidence_ids=("E2",),
            ),
        ),
        evidence=(new_evidence,),
        tool_ids_used=("vector.search",),
    )

    result.validate_for(task, descriptor)


def test_result_rejects_tool_used_without_both_allowlists() -> None:
    task = AgentTask(
        task_id="task-1",
        question="Question",
        objective="Objective",
        allowed_tool_ids=("vector.search",),
    )
    descriptor = AgentDescriptor(
        agent_id="literature",
        name="Literature specialist",
        responsibility="Find references.",
        capabilities=("references",),
        allowed_tool_ids=("graph.query",),
    )
    result = AgentResult(
        task_id="task-1",
        agent_id="literature",
        status=AgentStatus.SUCCEEDED,
        summary="Result",
        tool_ids_used=("graph.query",),
    )

    with pytest.raises(ValueError, match="outside the intersection"):
        result.validate_for(task, descriptor)


def test_failed_agent_result_requires_an_error_reason() -> None:
    with pytest.raises(ValueError, match="must include error_code or error_message"):
        AgentResult(
            task_id="task-1",
            agent_id="agent-1",
            status=AgentStatus.FAILED,
            summary="",
        )


def test_contract_rejects_non_json_context() -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        AgentTask(
            task_id="task-1",
            question="Question",
            objective="Objective",
            context={"invalid": object()},
        )
