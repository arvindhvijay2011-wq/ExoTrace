"""Integration tests for provenance-preserving orchestration into quantitative analysis."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from exotrace.agents.contracts import AgentDescriptor, AgentResult, AgentStatus, AgentTask
from exotrace.agents.orchestrator import (
    InvestigationOrchestrator,
    InvestigationStatus,
    OrchestratorConfig,
)
from exotrace.agents.planning import InvestigationPlan, PlanDisposition, PlannedAgentTask
from exotrace.agents.quantitative_analysis import QuantitativeAnalysisAgent
from exotrace.agents.registry import AgentRegistry
from exotrace.contracts import EvidenceReference, Finding
from exotrace.tools.contracts import (
    ToolDescriptor,
    ToolExecutor,
    ToolRequest,
    ToolResult,
    ToolStatus,
)
from exotrace.tools.quantitative_calculator import QuantitativeCalculatorTool
from exotrace.tools.registry import ToolRegistry


class NumericSourceTool:
    """Deterministic test source tool returning structured, traceable measurements."""

    TOOL_ID = "test.numeric_source"

    def __init__(self, records: Mapping[str, str]) -> None:
        self._records = dict(records)

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            tool_id=self.TOOL_ID,
            name="Test numeric source",
            purpose="Return one structured source record for an exact fixture target.",
            capabilities=("test.numeric_source",),
            input_schema={
                "type": "object",
                "properties": {"target": {"type": "string", "minLength": 1}},
                "required": ["target"],
                "additionalProperties": False,
            },
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        target = request.arguments["target"]
        if target not in self._records:
            return ToolResult(
                call_id=request.call_id,
                tool_id=request.tool_id,
                status=ToolStatus.FAILED,
                message=f"No fixture record for {target!r}.",
                error_code="record_not_found",
            )
        value = self._records[target]
        evidence = EvidenceReference(
            evidence_id=f"fixture:{target}",
            source_id=f"fixture-source:{target}",
            title=f"Source record for {target}",
            excerpt=json.dumps({"measurement": value}, separators=(",", ":")),
            source_uri=f"https://example.invalid/records/{target}",
            source_kind="test_catalogue_record",
            snapshot_id="fixture-snapshot-v1",
            record_id=f"fixture-record:{target}",
            metadata={
                "selected_fields": ["measurement"],
                "declared_unit": "km",
            },
        )
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.SUCCEEDED,
            data={"target": target},
            evidence=(evidence,),
        )


class NumericLookupAgent:
    """Test specialist that retrieves one structured record and returns its evidence."""

    def __init__(self, agent_id: str, source_tool_id: str) -> None:
        self._descriptor = AgentDescriptor(
            agent_id=agent_id,
            name=f"Numeric lookup {agent_id}",
            responsibility="Retrieve a single explicitly selected source record.",
            capabilities=("catalogue.lookup", "source.provenance"),
            allowed_tool_ids=(source_tool_id,),
            task_context_schema={
                "type": "object",
                "properties": {"target": {"type": "string", "minLength": 1}},
                "required": ["target"],
                "additionalProperties": False,
            },
        )
        self._source_tool_id = source_tool_id

    @property
    def descriptor(self) -> AgentDescriptor:
        return self._descriptor

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        result = tools.execute(
            ToolRequest(
                call_id=f"{task.task_id}:{self._source_tool_id}",
                tool_id=self._source_tool_id,
                arguments={"target": task.context["target"]},
            )
        )
        if result.status is ToolStatus.FAILED:
            return AgentResult(
                task_id=task.task_id,
                agent_id=self._descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="Source lookup failed.",
                error_code=result.error_code or "lookup_failed",
                error_message=result.message or "Lookup failed.",
                tool_ids_used=(self._source_tool_id,),
            )
        finding = Finding(
            finding_id=f"{task.task_id}:record",
            statement="Retrieved a structured source record.",
            finding_type="catalogue_record_values",
            evidence_ids=(result.evidence[0].evidence_id,),
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self._descriptor.agent_id,
            status=AgentStatus.SUCCEEDED,
            summary="Retrieved one structured source record.",
            findings=(finding,),
            evidence=result.evidence,
            tool_ids_used=(self._source_tool_id,),
        )


class StaticPlanner:
    """Inject a fixed plan so the handoff test makes no planner API calls."""

    model = "offline-test-planner"

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
        return self._plan


def test_catalogue_results_are_handed_off_to_quantitative_agent_end_to_end() -> None:
    source_tool = NumericSourceTool({"A": "8.5000000000000001", "B": "3.25"})
    calculator_tool = QuantitativeCalculatorTool()
    lookup_a = NumericLookupAgent("lookup_a", source_tool.TOOL_ID)
    lookup_b = NumericLookupAgent("lookup_b", source_tool.TOOL_ID)
    quantitative_agent = QuantitativeAnalysisAgent(calculator_tool)

    plan = InvestigationPlan(
        question="Calculate the difference between measurements A and B.",
        disposition=PlanDisposition.READY,
        summary="Retrieve both source records, then calculate their difference.",
        tasks=(
            PlannedAgentTask(
                task_key="measurement-a",
                agent_id="lookup_a",
                question="Retrieve measurement A.",
                objective="Return the structured record for A.",
                required_capabilities=("catalogue.lookup",),
                context={"target": "A"},
            ),
            PlannedAgentTask(
                task_key="measurement-b",
                agent_id="lookup_b",
                question="Retrieve measurement B.",
                objective="Return the structured record for B.",
                required_capabilities=("catalogue.lookup",),
                context={"target": "B"},
            ),
            PlannedAgentTask(
                task_key="measurement-difference",
                agent_id=QuantitativeAnalysisAgent.AGENT_ID,
                question="Calculate A minus B using the retrieved values.",
                objective="Calculate the difference using only the two prior source records.",
                required_capabilities=(QuantitativeAnalysisAgent.CAPABILITY_ID,),
                depends_on=("measurement-a", "measurement-b"),
                context={
                    "calculations": [
                        {
                            "calculation_id": "a-minus-b",
                            "operation": "difference",
                            "operands": [
                                {"source_task_key": "measurement-a", "field": "measurement"},
                                {"source_task_key": "measurement-b", "field": "measurement"},
                            ],
                        }
                    ]
                },
            ),
        ),
        planner_model="offline-test-planner",
    )
    orchestrator = InvestigationOrchestrator(
        agent_registry=AgentRegistry((lookup_a, lookup_b, quantitative_agent)),
        tool_registry=ToolRegistry((source_tool, calculator_tool)),
        planner=StaticPlanner(plan),
        config=OrchestratorConfig(max_agent_tasks=4),
    )

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.COMPLETED
    assert [result.status for result in report.results] == [
        AgentStatus.SUCCEEDED,
        AgentStatus.SUCCEEDED,
        AgentStatus.SUCCEEDED,
    ]
    quantitative_result = report.results[-1]
    assert quantitative_result.findings[0].data["value_exact"] == "5.2500000000000001"
    assert quantitative_result.findings[0].data["input_evidence_ids"] == [
        "fixture:A",
        "fixture:B",
    ]
    handed_off_keys = {
        item.metadata["exotrace_producer_task_key"]
        for item in quantitative_result.evidence
        if item.evidence_id in {"fixture:A", "fixture:B"}
    }
    assert handed_off_keys == {"measurement-a", "measurement-b"}
    derived = quantitative_result.evidence[-1]
    assert derived.metadata["exotrace_producer_task_key"] == "measurement-difference"


def test_quantitative_agent_cannot_use_evidence_from_an_unrelated_task() -> None:
    source_tool = NumericSourceTool({"A": "8.5", "B": "3.25"})
    calculator_tool = QuantitativeCalculatorTool()
    lookup_a = NumericLookupAgent("lookup_a", source_tool.TOOL_ID)
    lookup_b = NumericLookupAgent("lookup_b", source_tool.TOOL_ID)
    quantitative_agent = QuantitativeAnalysisAgent(calculator_tool)

    plan = InvestigationPlan(
        question="Calculate using an undeclared source dependency.",
        disposition=PlanDisposition.READY,
        summary="The quantitative task intentionally omits one dependency.",
        tasks=(
            PlannedAgentTask(
                task_key="measurement-a",
                agent_id="lookup_a",
                question="Retrieve A.",
                objective="Return record A.",
                required_capabilities=("catalogue.lookup",),
                context={"target": "A"},
            ),
            PlannedAgentTask(
                task_key="measurement-b",
                agent_id="lookup_b",
                question="Retrieve B.",
                objective="Return record B.",
                required_capabilities=("catalogue.lookup",),
                context={"target": "B"},
            ),
            PlannedAgentTask(
                task_key="measurement-difference",
                agent_id=QuantitativeAnalysisAgent.AGENT_ID,
                question="Calculate A minus B.",
                objective="Calculate using only declared dependency records.",
                required_capabilities=(QuantitativeAnalysisAgent.CAPABILITY_ID,),
                depends_on=("measurement-a",),
                context={
                    "calculations": [
                        {
                            "calculation_id": "a-minus-b",
                            "operation": "difference",
                            "operands": [
                                {"source_task_key": "measurement-a", "field": "measurement"},
                                {"source_task_key": "measurement-b", "field": "measurement"},
                            ],
                        }
                    ]
                },
            ),
        ),
        planner_model="offline-test-planner",
    )
    orchestrator = InvestigationOrchestrator(
        agent_registry=AgentRegistry((lookup_a, lookup_b, quantitative_agent)),
        tool_registry=ToolRegistry((source_tool, calculator_tool)),
        planner=StaticPlanner(plan),
        config=OrchestratorConfig(max_agent_tasks=4),
    )

    report = orchestrator.investigate(plan.question)

    assert report.results[-1].status is AgentStatus.FAILED
    assert report.results[-1].error_code == "calculation_operand_resolution_failed"
    assert "measurement-b" in (report.results[-1].error_message or "")
