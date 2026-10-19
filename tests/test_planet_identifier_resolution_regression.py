"""Regression tests for source-backed planet identifier correction in investigation plans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections.abc import Sequence

from exotrace.agents.catalogue_data import CatalogueDataAgent
from exotrace.agents.contracts import AgentDescriptor
from exotrace.agents.graph_investigation import GraphInvestigationAgent
from exotrace.agents.orchestrator import InvestigationOrchestrator
from exotrace.agents.planning import (
    InvestigationPlan,
    PlanDisposition,
    PlannedAgentTask,
)
from exotrace.agents.planet_identifier_resolution import CataloguePlanetIdentifierResolver
from exotrace.agents.registry import AgentRegistry
from exotrace.tools.catalogue_lookup import (
    CatalogueLookupConfig,
    CatalogueRecordLookupTool,
)
from exotrace.tools.contracts import ToolDescriptor, ToolRequest, ToolResult
from exotrace.tools.graph_investigation import GraphInvestigationTool
from exotrace.tools.registry import ToolRegistry

PLANET_NAME = "2MASS J03590986+2009361 b"
HOST_NAME = "2MASS J03590986+2009361"
QUESTION = f"Tell me something about this planet {PLANET_NAME}."


class _DescriptorOnlyTool:
    """Provide a registry descriptor without permitting tool execution in plan-only tests."""

    def __init__(self, descriptor: ToolDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def execute(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("Planning tests must not execute specialist tools.")


class _StaticPlanner:
    """Return a fixed valid-shaped plan so the orchestrator path can be tested offline."""

    model = "offline-regression-planner"

    def __init__(self, plan: InvestigationPlan) -> None:
        self._plan = plan

    def create_plan(
        self,
        question: str,
        *,
        agents: Sequence[AgentDescriptor],
        tools: Sequence[ToolDescriptor],
        max_tasks: int,
    ) -> InvestigationPlan:
        assert question == self._plan.question
        return self._plan


def _plan(
    question: str,
    *,
    catalogue_value: str = HOST_NAME,
    graph_value: str = HOST_NAME,
    graph_operation: str = "planet_context",
) -> InvestigationPlan:
    """Create two planning tasks that expose the historically truncated identifier."""
    tasks = (
        PlannedAgentTask(
            agent_id="catalogue_data",
            question=question,
            objective="Retrieve the exact planet catalogue record.",
            required_capabilities=("catalogue.raw_values",),
            context={
                "filters": [{"field": "pl_name", "value": catalogue_value}],
                "match_mode": "exact",
                "limit": 1,
            },
            task_key="catalogue-planet",
        ),
        PlannedAgentTask(
            agent_id="graph_investigation",
            question=question,
            objective="Retrieve graph context for the requested planet.",
            required_capabilities=("graph.relationships",),
            context={"operation": graph_operation, "planet_name": graph_value, "result_limit": 1},
            task_key="graph-planet",
        ),
    )
    return InvestigationPlan(
        question=question,
        disposition=PlanDisposition.READY,
        summary="Retrieve the catalogue record and graph context.",
        tasks=tasks,
        planner_model="offline-regression-planner",
    )


def _resolver(
    identities: tuple[tuple[str, str], ...] | None = None,
) -> CataloguePlanetIdentifierResolver:
    return CataloguePlanetIdentifierResolver(
        identities or ((PLANET_NAME, HOST_NAME),)
    )


def _descriptor_tool(tool_id: str, name: str) -> _DescriptorOnlyTool:
    return _DescriptorOnlyTool(
        ToolDescriptor(
            tool_id=tool_id,
            name=name,
            purpose="Descriptor-only tool for plan validation tests.",
            capabilities=("source.provenance",),
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
    )


def test_orchestrator_corrects_truncated_identifiers_from_explicit_catalogue_name() -> None:
    """A full name in the question repairs both contexts before execution is planned."""
    original_plan = _plan(QUESTION)
    agents = AgentRegistry(
        (
            CatalogueDataAgent(available_fields=("pl_name", "hostname")),
            GraphInvestigationAgent(),
        )
    )
    tools = ToolRegistry(
        (
            _descriptor_tool(CatalogueRecordLookupTool.TOOL_ID, "Catalogue lookup"),
            _descriptor_tool(GraphInvestigationTool.TOOL_ID, "Graph investigation"),
        )
    )
    orchestrator = InvestigationOrchestrator(
        agent_registry=agents,
        tool_registry=tools,
        planner=_StaticPlanner(original_plan),
        plan_context_resolver=_resolver().resolve_plan,
    )

    resolved = orchestrator.create_plan(QUESTION)

    assert resolved.tasks[0].context["filters"] == [
        {"field": "pl_name", "value": PLANET_NAME}
    ]
    assert resolved.tasks[1].context["planet_name"] == PLANET_NAME
    assert resolved.question == original_plan.question
    assert resolved.tasks[0].task_key == original_plan.tasks[0].task_key
    assert resolved.tasks[1].task_key == original_plan.tasks[1].task_key
    assert original_plan.tasks[0].context["filters"][0]["value"] == HOST_NAME
    assert original_plan.tasks[1].context["planet_name"] == HOST_NAME


def test_ambiguous_planets_sharing_one_host_are_not_rewritten() -> None:
    """Two explicitly named planets around one host must not collapse to either planet."""
    second_planet = "2MASS J03590986+2009361 c"
    resolver = _resolver(((PLANET_NAME, HOST_NAME), (second_planet, HOST_NAME)))
    question = f"Compare {PLANET_NAME} and {second_planet}."
    original_plan = _plan(question)

    resolved = resolver.resolve_plan(original_plan)

    assert resolved is original_plan
    assert resolved.tasks[0].context["filters"][0]["value"] == HOST_NAME
    assert resolved.tasks[1].context["planet_name"] == HOST_NAME


def test_host_planets_operation_keeps_host_identifier_even_when_planet_is_named() -> None:
    """The overloaded legacy graph argument must not rewrite an explicitly selected host."""
    original_plan = _plan(QUESTION, graph_operation="host_planets")

    resolved = _resolver().resolve_plan(original_plan)

    assert resolved.tasks[0].context["filters"][0]["value"] == PLANET_NAME
    assert resolved.tasks[1].context["operation"] == "host_planets"
    assert resolved.tasks[1].context["planet_name"] == HOST_NAME


def test_host_name_without_full_planet_mention_is_not_guessed() -> None:
    """A host-only question does not provide evidence to choose one of its planets."""
    question = f"Tell me something about {HOST_NAME}."
    original_plan = _plan(question)

    resolved = _resolver().resolve_plan(original_plan)

    assert resolved is original_plan
    assert resolved.tasks[0].context["filters"][0]["value"] == HOST_NAME
    assert resolved.tasks[1].context["planet_name"] == HOST_NAME


def test_catalogue_identity_pairs_come_from_the_verified_snapshot(tmp_path: Path) -> None:
    """The exposed identity pairs retain exact values from the manifest-checked CSV."""
    catalogue_path = tmp_path / "planets_validated.csv"
    report_path = tmp_path / "validation_report.json"
    csv_bytes = (
        "pl_name,hostname\n"
        f'"{PLANET_NAME}","{HOST_NAME}"\n'
    ).encode("utf-8")
    catalogue_path.write_bytes(csv_bytes)
    report_path.write_text(
        json.dumps(
            {
                "passed": True,
                "processed_sha256": hashlib.sha256(csv_bytes).hexdigest(),
                "row_count": 1,
            }
        ),
        encoding="utf-8",
    )
    tool = CatalogueRecordLookupTool(
        config=CatalogueLookupConfig(
            catalogue_path=catalogue_path,
            validation_report_path=report_path,
        )
    )

    assert tool.planet_host_identities == ((PLANET_NAME, HOST_NAME),)
