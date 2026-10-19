"""Offline tests for dynamic task orchestration and specialist boundaries."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from exotrace.agents.contracts import (
    AgentDescriptor,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from exotrace.agents.investigate import render_investigation_report
from exotrace.agents.orchestrator import (
    InvestigationOrchestrator,
    InvestigationStatus,
    OrchestrationError,
    OrchestratorConfig,
    validate_context_against_schema,
)
from exotrace.agents.planning import (
    InvestigationPlan,
    PlanDisposition,
    PlannedAgentTask,
)
from exotrace.agents.registry import AgentRegistry
from exotrace.contracts import EvidenceReference, Finding
from exotrace.tools.contracts import (
    ExoTraceTool,
    ToolDescriptor,
    ToolExecutor,
    ToolRequest,
    ToolResult,
    ToolStatus,
)
from exotrace.tools.registry import ToolRegistry


TASK_CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "minLength": 1},
        "mode": {"type": "string", "enum": ["exact", "contains"]},
    },
    "required": ["target"],
    "additionalProperties": False,
}


def test_context_schema_accepts_description_annotation_on_a_property() -> None:
    """Descriptions are schema metadata and must not block valid task contexts."""
    schema = {
        "type": "object",
        "properties": {
            "planet_name": {
                "type": "string",
                "minLength": 1,
                "description": "Name of the planet to investigate.",
            }
        },
        "required": ["planet_name"],
        "additionalProperties": False,
    }

    validate_context_against_schema({"planet_name": "Kepler-10"}, schema)


class EchoTool:
    """Small deterministic tool used to test restricted orchestration offline."""

    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id
        self.calls: list[ToolRequest] = []

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            tool_id=self._tool_id,
            name=f"Echo {self._tool_id}",
            purpose="Return the requested target as source-backed test evidence.",
            capabilities=("test.echo",),
            input_schema={
                "type": "object",
                "properties": {"target": {"type": "string", "minLength": 1}},
                "required": ["target"],
                "additionalProperties": False,
            },
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        target = request.arguments["target"]
        evidence = EvidenceReference(
            evidence_id=f"{self._tool_id}:{target}",
            source_id=f"source:{target}",
            title=f"Source for {target}",
            excerpt=f"Verified test text for {target}.",
            source_uri="https://example.test/source",
            source_kind="test_source",
        )
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.SUCCEEDED,
            data={"target": target},
            evidence=(evidence,),
        )


class RecordingAgent:
    """A narrow test specialist that calls only its declared tool."""

    def __init__(self, agent_id: str, tool_id: str, *, fail: bool = False) -> None:
        self._descriptor = AgentDescriptor(
            agent_id=agent_id,
            name=f"Agent {agent_id}",
            responsibility=f"Perform one test task with {tool_id}.",
            capabilities=("test.lookup",),
            allowed_tool_ids=(tool_id,),
            task_context_schema=TASK_CONTEXT_SCHEMA,
        )
        self._fail = fail
        self.calls = 0

    @property
    def descriptor(self) -> AgentDescriptor:
        return self._descriptor

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        self.calls += 1
        if self._fail:
            raise RuntimeError("synthetic specialist failure")
        tool_id = self._descriptor.allowed_tool_ids[0]
        result = tools.execute(
            ToolRequest(
                call_id=f"{task.task_id}:{tool_id}",
                tool_id=tool_id,
                arguments={"target": task.context["target"]},
            )
        )
        evidence = result.evidence
        finding = Finding(
            finding_id=f"{task.task_id}:finding",
            statement=f"Retrieved the source for {task.context['target']}.",
            finding_type="test_finding",
            evidence_ids=(evidence[0].evidence_id,),
        )
        return AgentResult(
            task_id=task.task_id,
            agent_id=self._descriptor.agent_id,
            status=AgentStatus.SUCCEEDED,
            summary="Test specialist completed the task.",
            findings=(finding,),
            evidence=evidence,
            tool_ids_used=(tool_id,),
        )


class InputCapturingAgent(RecordingAgent):
    """Recording specialist that exposes the evidence delivered by declared dependencies."""

    def __init__(self, agent_id: str, tool_id: str, *, fail: bool = False) -> None:
        super().__init__(agent_id, tool_id, fail=fail)
        self.received_inputs: tuple[EvidenceReference, ...] = ()

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        self.received_inputs = task.input_evidence
        return super().run(task, tools=tools)


class StaticPlanner:
    """Inject a preconfigured plan without making a model call."""

    model = "offline-test-planner"

    def __init__(self, plan: InvestigationPlan) -> None:
        self.plan = plan
        self.calls: list[dict[str, Any]] = []

    def create_plan(
        self,
        question: str,
        *,
        agents: Sequence[AgentDescriptor],
        tools: Sequence[ToolDescriptor],
        max_tasks: int,
    ) -> InvestigationPlan:
        self.calls.append(
            {
                "question": question,
                "agents": list(agents),
                "tools": list(tools),
                "max_tasks": max_tasks,
            }
        )
        return self.plan


def make_plan(
    question: str = "Find source evidence for both targets.",
    tasks: tuple[PlannedAgentTask, ...] | None = None,
) -> InvestigationPlan:
    """Create a two-agent plan used by orchestration tests."""
    planned_tasks = tasks or (
        PlannedAgentTask(
            agent_id="literature_test",
            question="Retrieve source for target A.",
            objective="Retrieve source-backed evidence for target A.",
            required_capabilities=("test.lookup",),
            context={"target": "A"},
        ),
        PlannedAgentTask(
            agent_id="catalogue_test",
            question="Retrieve source for target B.",
            objective="Retrieve source-backed evidence for target B.",
            required_capabilities=("test.lookup",),
            context={"target": "B"},
        ),
    )
    return InvestigationPlan(
        question=question,
        disposition=PlanDisposition.READY,
        summary="Delegate two independent source lookups.",
        tasks=planned_tasks,
        planner_model="offline-test-planner",
    )


def make_orchestrator(
    plan: InvestigationPlan,
    *,
    fail_first: bool = False,
    max_tasks: int = 5,
) -> tuple[
    InvestigationOrchestrator,
    dict[str, RecordingAgent],
    dict[str, EchoTool],
    StaticPlanner,
]:
    """Build a fully offline orchestrator with two isolated specialists."""
    first_tool = EchoTool("literature.echo")
    second_tool = EchoTool("catalogue.echo")
    first_agent = RecordingAgent("literature_test", first_tool.descriptor.tool_id, fail=fail_first)
    second_agent = RecordingAgent("catalogue_test", second_tool.descriptor.tool_id)
    agent_registry = AgentRegistry((first_agent, second_agent))
    tool_registry = ToolRegistry((first_tool, second_tool))
    planner = StaticPlanner(plan)
    orchestrator = InvestigationOrchestrator(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        planner=planner,
        config=OrchestratorConfig(max_agent_tasks=max_tasks),
    )
    return (
        orchestrator,
        {
            first_agent.descriptor.agent_id: first_agent,
            second_agent.descriptor.agent_id: second_agent,
        },
        {first_tool.descriptor.tool_id: first_tool, second_tool.descriptor.tool_id: second_tool},
        planner,
    )


def test_orchestrator_runs_only_the_agents_selected_by_the_plan() -> None:
    plan = make_plan(
        tasks=(
            PlannedAgentTask(
                agent_id="catalogue_test",
                question="Retrieve target B.",
                objective="Retrieve the source for target B.",
                required_capabilities=("test.lookup",),
                context={"target": "B"},
            ),
        )
    )
    orchestrator, agents, tools, _planner = make_orchestrator(plan)

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.COMPLETED
    assert len(report.results) == 1
    assert report.results[0].agent_id == "catalogue_test"
    assert agents["catalogue_test"].calls == 1
    assert agents["literature_test"].calls == 0
    assert len(tools["catalogue.echo"].calls) == 1
    assert not tools["literature.echo"].calls


def test_orchestrator_keeps_findings_and_source_provenance_in_report() -> None:
    plan = make_plan()
    orchestrator, _agents, _tools, _planner = make_orchestrator(plan)

    report = orchestrator.investigate(plan.question)
    serialized = report.to_dict()

    assert report.status is InvestigationStatus.COMPLETED
    assert len(serialized["results"]) == 2
    assert serialized["results"][0]["findings"][0]["evidence_ids"]
    assert serialized["results"][0]["evidence"][0]["source_uri"] == (
        "https://example.test/source"
    )
    assert serialized["plan"]["planner_model"] == "offline-test-planner"


def test_plan_only_does_not_execute_any_specialists() -> None:
    plan = make_plan()
    orchestrator, agents, tools, _planner = make_orchestrator(plan)

    report = orchestrator.investigate(plan.question, execute=False)

    assert report.status is InvestigationStatus.PLANNED
    assert not report.results
    assert all(agent.calls == 0 for agent in agents.values())
    assert all(not tool.calls for tool in tools.values())


def test_planner_clarification_state_returns_without_executing_agents() -> None:
    plan = InvestigationPlan(
        question="Compare it with the other planet.",
        disposition=PlanDisposition.NEEDS_CLARIFICATION,
        summary="The second planet is not identified.",
        clarifying_questions=("Which second planet should be compared?",),
        planner_model="offline-test-planner",
    )
    orchestrator, agents, tools, _planner = make_orchestrator(plan)

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.NEEDS_CLARIFICATION
    assert report.results == ()
    assert all(agent.calls == 0 for agent in agents.values())
    assert all(not tool.calls for tool in tools.values())


def test_unsupported_plan_returns_without_executing_agents() -> None:
    plan = InvestigationPlan(
        question="Control the telescope hardware.",
        disposition=PlanDisposition.UNSUPPORTED,
        summary="No registered specialist has hardware-control capability.",
        planner_model="offline-test-planner",
    )
    orchestrator, agents, tools, _planner = make_orchestrator(plan)

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.UNSUPPORTED
    assert not report.results
    assert all(agent.calls == 0 for agent in agents.values())
    assert all(not tool.calls for tool in tools.values())


def test_orchestrator_rejects_an_unregistered_agent() -> None:
    plan = make_plan(
        tasks=(
            PlannedAgentTask(
                agent_id="unknown_agent",
                question="Question",
                objective="Objective",
                required_capabilities=("test.lookup",),
                context={"target": "A"},
            ),
        )
    )
    orchestrator, _agents, _tools, _planner = make_orchestrator(plan)

    with pytest.raises(OrchestrationError, match="unregistered agent"):
        orchestrator.create_plan(plan.question)


def test_orchestrator_rejects_capabilities_outside_agent_contract() -> None:
    plan = make_plan(
        tasks=(
            PlannedAgentTask(
                agent_id="literature_test",
                question="Question",
                objective="Objective",
                required_capabilities=("graph.write",),
                context={"target": "A"},
            ),
        )
    )
    orchestrator, _agents, _tools, _planner = make_orchestrator(plan)

    with pytest.raises(OrchestrationError, match="undeclared capability"):
        orchestrator.create_plan(plan.question)


def test_orchestrator_rejects_context_keys_not_declared_by_agent() -> None:
    plan = make_plan(
        tasks=(
            PlannedAgentTask(
                agent_id="literature_test",
                question="Question",
                objective="Objective",
                required_capabilities=("test.lookup",),
                context={"target": "A", "arbitrary_tool": "unsafe"},
            ),
        )
    )
    orchestrator, _agents, _tools, _planner = make_orchestrator(plan)

    with pytest.raises(OrchestrationError, match="unsupported field"):
        orchestrator.create_plan(plan.question)


def test_orchestrator_rejects_invalid_context_enum_before_calling_tool() -> None:
    plan = make_plan(
        tasks=(
            PlannedAgentTask(
                agent_id="literature_test",
                question="Question",
                objective="Objective",
                required_capabilities=("test.lookup",),
                context={"target": "A", "mode": "delete"},
            ),
        )
    )
    orchestrator, agents, tools, _planner = make_orchestrator(plan)

    with pytest.raises(OrchestrationError, match="not in the allowed enum"):
        orchestrator.create_plan(plan.question)
    assert agents["literature_test"].calls == 0
    assert all(not tool.calls for tool in tools.values())


def test_specialist_failure_does_not_prevent_later_tasks_from_running() -> None:
    plan = make_plan()
    orchestrator, agents, tools, _planner = make_orchestrator(plan, fail_first=True)

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.PARTIAL
    assert report.results[0].status is AgentStatus.FAILED
    assert report.results[1].status is AgentStatus.SUCCEEDED
    assert agents["catalogue_test"].calls == 1
    assert len(tools["catalogue.echo"].calls) == 1


def test_orchestrator_enforces_configured_task_budget() -> None:
    plan = make_plan("Find source evidence for both targets.")
    orchestrator, _agents, _tools, _planner = make_orchestrator(plan, max_tasks=1)

    with pytest.raises(OrchestrationError, match="configured maximum"):
        orchestrator.create_plan(plan.question)


def test_report_status_is_insufficient_when_all_specialists_lack_evidence() -> None:
    # Build fake specialist implementations that return explicit insufficiency.
    class EmptyAgent(RecordingAgent):
        def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
            self.calls += 1
            return AgentResult(
                task_id=task.task_id,
                agent_id=self.descriptor.agent_id,
                status=AgentStatus.INSUFFICIENT_EVIDENCE,
                summary="No evidence matched.",
                gaps=("No matching source record.",),
            )

    plan = make_plan(
        tasks=(
            PlannedAgentTask(
                agent_id="empty_one",
                question="Q1",
                objective="Find source one.",
                required_capabilities=("test.lookup",),
                context={"target": "A"},
            ),
        )
    )
    tool = EchoTool("tool.one")
    agent = EmptyAgent("empty_one", "tool.one")
    orchestrator = InvestigationOrchestrator(
        agent_registry=AgentRegistry((agent,)),
        tool_registry=ToolRegistry((tool,)),
        planner=StaticPlanner(plan),
    )

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.INSUFFICIENT_EVIDENCE
    assert report.results[0].gaps


def test_report_renderer_shows_plan_results_and_provenance() -> None:
    plan = make_plan()
    orchestrator, _agents, _tools, _planner = make_orchestrator(plan)
    report = orchestrator.investigate(plan.question)

    rendered = render_investigation_report(report, orchestrator)

    assert "ExoTrace investigation report" in rendered
    assert "Planned specialist tasks" in rendered
    assert "Specialist results" in rendered
    assert "https://example.test/source" in rendered
    assert "not the final synthesized scientific answer" in rendered


def test_reviewed_plan_execution_does_not_call_planner_again() -> None:
    plan = make_plan(
        tasks=(
            PlannedAgentTask(
                agent_id="catalogue_test",
                question="Retrieve target B.",
                objective="Retrieve the source for target B.",
                required_capabilities=("test.lookup",),
                context={"target": "B"},
            ),
        )
    )
    orchestrator, _agents, _tools, planner = make_orchestrator(plan)

    reviewed_plan = orchestrator.create_plan(plan.question)
    report = orchestrator.execute_plan(reviewed_plan)

    assert report.status is InvestigationStatus.COMPLETED
    assert len(planner.calls) == 1


def test_orchestrator_hands_off_only_declared_dependency_outputs_with_provenance() -> None:
    first_tool = EchoTool("source.echo")
    second_tool = EchoTool("consumer.echo")
    first_agent = RecordingAgent("source_agent", first_tool.descriptor.tool_id)
    second_agent = InputCapturingAgent("consumer_agent", second_tool.descriptor.tool_id)
    plan = InvestigationPlan(
        question="Find source evidence then inspect the source result.",
        disposition=PlanDisposition.READY,
        summary="The second task depends on the first task's output.",
        tasks=(
            PlannedAgentTask(
                task_key="source-lookup",
                agent_id="source_agent",
                question="Retrieve source A.",
                objective="Return evidence for source A.",
                required_capabilities=("test.lookup",),
                context={"target": "A"},
            ),
            PlannedAgentTask(
                task_key="dependent-inspection",
                agent_id="consumer_agent",
                question="Inspect the evidence returned by source A.",
                objective="Use the source evidence from the prerequisite task.",
                required_capabilities=("test.lookup",),
                context={"target": "B"},
                depends_on=("source-lookup",),
            ),
        ),
        planner_model="offline-test-planner",
    )
    orchestrator = InvestigationOrchestrator(
        agent_registry=AgentRegistry((first_agent, second_agent)),
        tool_registry=ToolRegistry((first_tool, second_tool)),
        planner=StaticPlanner(plan),
    )

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.COMPLETED
    assert len(second_agent.received_inputs) == 1
    received = second_agent.received_inputs[0]
    assert received.evidence_id == "source.echo:A"
    assert received.metadata["exotrace_producer_task_key"] == "source-lookup"
    assert received.metadata["exotrace_producer_agent_id"] == "source_agent"
    assert report.results[0].evidence[0].metadata["exotrace_producer_task_key"] == "source-lookup"


def test_orchestrator_does_not_handoff_evidence_from_undeclared_tasks() -> None:
    first_tool = EchoTool("independent-source.echo")
    second_tool = EchoTool("independent-consumer.echo")
    first_agent = RecordingAgent("independent_source", first_tool.descriptor.tool_id)
    second_agent = InputCapturingAgent("independent_consumer", second_tool.descriptor.tool_id)
    plan = InvestigationPlan(
        question="Run independent source tasks.",
        disposition=PlanDisposition.READY,
        summary="Both tasks are independent.",
        tasks=(
            PlannedAgentTask(
                task_key="source-one",
                agent_id="independent_source",
                question="Find A.",
                objective="Return evidence for A.",
                required_capabilities=("test.lookup",),
                context={"target": "A"},
            ),
            PlannedAgentTask(
                task_key="consumer-two",
                agent_id="independent_consumer",
                question="Find B.",
                objective="Return evidence for B independently.",
                required_capabilities=("test.lookup",),
                context={"target": "B"},
            ),
        ),
        planner_model="offline-test-planner",
    )
    orchestrator = InvestigationOrchestrator(
        agent_registry=AgentRegistry((first_agent, second_agent)),
        tool_registry=ToolRegistry((first_tool, second_tool)),
        planner=StaticPlanner(plan),
    )

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.COMPLETED
    assert second_agent.received_inputs == ()


def test_failed_dependency_withholds_downstream_agent_execution() -> None:
    """A dependent task must not run when its prerequisite failed."""
    plan = make_plan(
        tasks=(
            PlannedAgentTask(
                task_key="source-task",
                agent_id="literature_test",
                question="Retrieve source A.",
                objective="Produce evidence required by the dependent task.",
                required_capabilities=("test.lookup",),
                context={"target": "A"},
            ),
            PlannedAgentTask(
                task_key="dependent-task",
                agent_id="catalogue_test",
                question="Inspect the source result.",
                objective="Use evidence produced by source-task.",
                required_capabilities=("test.lookup",),
                context={"target": "B"},
                depends_on=("source-task",),
            ),
        )
    )
    orchestrator, agents, _tools, _planner = make_orchestrator(plan, fail_first=True)

    report = orchestrator.investigate(plan.question)

    assert report.status is InvestigationStatus.FAILED
    assert report.results[0].status is AgentStatus.FAILED
    assert report.results[1].status is AgentStatus.FAILED
    assert "downstream execution was withheld" in (report.results[1].error_message or "")
    assert agents["literature_test"].calls == 1
    assert agents["catalogue_test"].calls == 0
