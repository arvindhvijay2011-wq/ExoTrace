"""Tests for ExoTrace's tool contracts, registry, and permission checks."""

from __future__ import annotations

import pytest

from exotrace.agents.contracts import AgentDescriptor, AgentTask
from exotrace.contracts import EvidenceReference
from exotrace.tools import (
    ToolAccessDenied,
    ToolDescriptor,
    ToolRegistry,
    ToolRegistryError,
    ToolRequest,
    ToolResult,
    ToolStatus,
)


class FakeTool:
    """Simple deterministic tool for registry tests; no network or databases used."""

    def __init__(self, descriptor: ToolDescriptor) -> None:
        self._descriptor = descriptor
        self.calls: list[ToolRequest] = []

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def execute(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.SUCCEEDED,
            data={"accepted_arguments": dict(request.arguments)},
        )


def make_tool(tool_id: str = "vector.search") -> FakeTool:
    """Return a fake read-only tool with a generic input schema."""
    return FakeTool(
        ToolDescriptor(
            tool_id=tool_id,
            name="Vector search",
            purpose="Search the configured scientific text corpus.",
            capabilities=("reference_retrieval",),
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            output_schema={"type": "object"},
            read_only=True,
        )
    )


def make_agent_descriptor(allowed_tool_ids: tuple[str, ...]) -> AgentDescriptor:
    """Return an agent descriptor for permission tests."""
    return AgentDescriptor(
        agent_id="literature",
        name="Literature specialist",
        responsibility="Find evidence in reference sources.",
        capabilities=("reference_retrieval",),
        allowed_tool_ids=allowed_tool_ids,
    )


def test_tool_request_and_result_round_trip() -> None:
    request = ToolRequest(
        call_id="call-1",
        tool_id="vector.search",
        arguments={"query": "planetary parameters", "top_k": 3},
    )
    result = ToolResult(
        call_id="call-1",
        tool_id="vector.search",
        status=ToolStatus.SUCCEEDED,
        data={"count": 1},
        evidence=(
            EvidenceReference(
                evidence_id="E1",
                source_id="source-1",
                title="Reference",
                excerpt="Relevant source text.",
            ),
        ),
    )

    assert request.to_dict()["arguments"]["top_k"] == 3
    assert result.to_dict()["status"] == "succeeded"
    assert result.to_dict()["evidence"][0]["source_id"] == "source-1"


def test_executor_allows_only_intersection_of_task_and_agent_allowlists() -> None:
    tool = make_tool()
    registry = ToolRegistry((tool,))
    agent = make_agent_descriptor(("vector.search", "not-granted-by-task"))
    task = AgentTask(
        task_id="task-1",
        question="Find a definition.",
        objective="Retrieve evidence.",
        allowed_tool_ids=("vector.search", "not-granted-by-agent"),
    )
    executor = registry.executor_for(agent, task)

    result = executor.execute(
        ToolRequest(
            call_id="call-1",
            tool_id="vector.search",
            arguments={"query": "definition"},
        )
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert executor.permitted_tool_ids == frozenset({"vector.search"})
    assert len(tool.calls) == 1


def test_executor_denies_tool_not_in_both_allowlists() -> None:
    tool = make_tool()
    registry = ToolRegistry((tool,))
    agent = make_agent_descriptor(("vector.search",))
    task = AgentTask(
        task_id="task-1",
        question="Find a definition.",
        objective="Retrieve evidence.",
        allowed_tool_ids=(),
    )
    executor = registry.executor_for(agent, task)

    with pytest.raises(ToolAccessDenied, match="not permitted"):
        executor.execute(
            ToolRequest(
                call_id="call-1",
                tool_id="vector.search",
                arguments={"query": "definition"},
            )
        )
    assert tool.calls == []


def test_registry_rejects_duplicate_tool_ids() -> None:
    with pytest.raises(ToolRegistryError, match="already registered"):
        ToolRegistry((make_tool(), make_tool()))


def test_registry_rejects_permission_for_unknown_tool() -> None:
    registry = ToolRegistry((make_tool(),))
    task = AgentTask(
        task_id="task-1",
        question="Question",
        objective="Objective",
        allowed_tool_ids=("missing.tool",),
    )
    agent = make_agent_descriptor(("missing.tool",))

    with pytest.raises(ToolRegistryError, match="unregistered tools"):
        registry.executor_for(agent, task)


def test_executor_rejects_mismatched_tool_result_identity() -> None:
    class IncorrectTool(FakeTool):
        """Broken tool that claims its response belongs to another call."""

        def execute(self, request: ToolRequest) -> ToolResult:
            return ToolResult(
                call_id="different-call",
                tool_id=request.tool_id,
                status=ToolStatus.SUCCEEDED,
                data={},
            )

    tool = IncorrectTool(make_tool().descriptor)
    registry = ToolRegistry((tool,))
    agent = make_agent_descriptor(("vector.search",))
    task = AgentTask(
        task_id="task-1",
        question="Question",
        objective="Objective",
        allowed_tool_ids=("vector.search",),
    )

    with pytest.raises(ToolRegistryError, match="identity does not match"):
        registry.executor_for(agent, task).execute(
            ToolRequest("call-1", "vector.search", {"query": "x"})
        )


def test_failed_tool_result_requires_error_reason() -> None:
    with pytest.raises(ValueError, match="must include error_code or message"):
        ToolResult(
            call_id="call-1",
            tool_id="vector.search",
            status=ToolStatus.FAILED,
        )
