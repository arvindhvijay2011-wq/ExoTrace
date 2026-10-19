"""Tests for LangGraph-native specialist task nodes and dependency edges."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Sequence

import pytest

from exotrace.agents.contracts import AgentResult, AgentStatus
from exotrace.agents.langgraph_workflow import (
    LangGraphDependencyError,
    LangGraphInvestigationWorkflow,
    build_investigation_graph,
    build_task_execution_graph,
)
from exotrace.agents.orchestrator import InvestigationReport, InvestigationStatus
from exotrace.agents.planning import (
    InvestigationPlan,
    PlanDisposition,
    PlannedAgentTask,
)
from exotrace.contracts import EvidenceReference

START = "__test_start__"
END = "__test_end__"


class FakeCompiledGraph:
    """Small deterministic DAG executor for offline workflow tests.

    It honours join edges and reducer-style dictionary merges. Independent nodes run serially in
    this fake for determinism, while tests assert the dependencies and evidence visible to each
    node. The real LangGraph API is exercised separately when the optional package is installed.
    """

    invocation_configs: list[Mapping[str, Any] | None] = []

    def __init__(
        self,
        nodes: Mapping[str, Callable[[dict[str, Any]], Mapping[str, Any]]],
        edge_groups: Sequence[tuple[tuple[str, ...], str]],
        conditional_edges: Mapping[
            str,
            tuple[Callable[[dict[str, Any]], str], Mapping[str, str]],
        ],
    ) -> None:
        self.nodes = dict(nodes)
        self.edge_groups = list(edge_groups)
        self.conditional_edges = dict(conditional_edges)

    def invoke(
        self,
        inputs: Mapping[str, Any],
        config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute reachable nodes and retain config for checkpoint-routing assertions."""
        self.invocation_configs.append(config)
        state = dict(inputs)
        completed: set[str] = set()
        active_edges = list(self.edge_groups)
        while True:
            if any(
                target == END and all(source in completed or source == START for source in sources)
                for sources, target in active_edges
            ):
                return state

            candidates = [
                name
                for name in self.nodes
                if name not in completed
                and any(
                    target == name and all(source in completed or source == START for source in sources)
                    for sources, target in active_edges
                )
            ]
            if not candidates:
                waiting = sorted(set(self.nodes) - completed)
                raise RuntimeError(
                    f"Fake LangGraph found no executable node; possible cycle or missing edge: {waiting}"
                )

            current = candidates[0]
            update = self.nodes[current](state)
            if not isinstance(update, Mapping):
                raise TypeError("Graph node updates must be mappings.")
            for key, value in update.items():
                existing = state.get(key)
                if isinstance(existing, dict) and isinstance(value, dict):
                    collisions = set(existing) & set(value)
                    if collisions:
                        raise RuntimeError(f"Duplicate reducer keys: {sorted(collisions)}")
                    state[key] = {**existing, **value}
                else:
                    state[key] = value
            completed.add(current)

            conditional = self.conditional_edges.get(current)
            if conditional is not None:
                router, path_map = conditional
                route = router(state)
                if route not in path_map:
                    raise RuntimeError(f"No fake graph edge for route {route!r}.")
                target = path_map[route]
                active_edges.append(((current,), target))


class FakeStateGraph:
    """Implement the subset of the public StateGraph builder API used by ExoTrace."""

    def __init__(self, _state_schema: type[Any]) -> None:
        self.nodes: dict[str, Callable[[dict[str, Any]], Mapping[str, Any]]] = {}
        self.edge_groups: list[tuple[tuple[str, ...], str]] = []
        self.conditional_edges: dict[
            str,
            tuple[Callable[[dict[str, Any]], str], Mapping[str, str]],
        ] = {}

    def add_node(
        self,
        node_name: str,
        action: Callable[[dict[str, Any]], Mapping[str, Any]],
    ) -> None:
        self.nodes[node_name] = action

    def add_edge(self, start_key: str | list[str], end_key: str) -> None:
        sources = tuple(start_key) if isinstance(start_key, list) else (start_key,)
        self.edge_groups.append((sources, end_key))

    def add_conditional_edges(
        self,
        start_key: str,
        router: Callable[[dict[str, Any]], str],
        path_map: Mapping[str, str],
    ) -> None:
        self.conditional_edges[start_key] = (router, dict(path_map))

    def compile(self, *, checkpointer: Any | None = None) -> FakeCompiledGraph:
        self.checkpointer = checkpointer
        return FakeCompiledGraph(self.nodes, self.edge_groups, self.conditional_edges)


def install_fake_langgraph(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject the test graph builder without changing production imports."""
    FakeCompiledGraph.invocation_configs = []
    parent_module = types.ModuleType("langgraph")
    parent_module.__path__ = []  # type: ignore[attr-defined]
    graph_module = types.ModuleType("langgraph.graph")
    graph_module.START = START  # type: ignore[attr-defined]
    graph_module.END = END  # type: ignore[attr-defined]
    graph_module.StateGraph = FakeStateGraph  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langgraph", parent_module)
    monkeypatch.setitem(sys.modules, "langgraph.graph", graph_module)


def make_task(
    task_key: str,
    *,
    dependencies: tuple[str, ...] = (),
    agent_id: str = "literature_definition",
) -> PlannedAgentTask:
    """Create one plan task for deterministic orchestration tests."""
    return PlannedAgentTask(
        agent_id=agent_id,
        question=f"Question for {task_key}",
        objective=f"Perform the task {task_key}.",
        required_capabilities=("literature.retrieve",),
        context={},
        task_key=task_key,
        depends_on=dependencies,
    )


def make_plan(
    question: str = "What is eccentricity?",
    *,
    disposition: PlanDisposition = PlanDisposition.READY,
    tasks: tuple[PlannedAgentTask, ...] | None = None,
) -> InvestigationPlan:
    """Build a valid deterministic investigation plan."""
    if disposition is PlanDisposition.READY:
        actual_tasks = tasks or (make_task("literature-1"),)
        clarifying_questions: tuple[str, ...] = ()
        summary = "Investigate using the selected specialist tasks."
    elif disposition is PlanDisposition.NEEDS_CLARIFICATION:
        actual_tasks = ()
        clarifying_questions = ("Please identify the intended catalogue entity.",)
        summary = "The entity needs clarification."
    else:
        actual_tasks = ()
        clarifying_questions = ()
        summary = "The request is unsupported."
    return InvestigationPlan(
        question=question,
        disposition=disposition,
        summary=summary,
        tasks=actual_tasks,
        clarifying_questions=clarifying_questions,
        planner_model="offline-test-planner",
    )


class StubOrchestrator:
    """Model the public single-task orchestration boundary without calling external services."""

    def __init__(self, plan: InvestigationPlan | None = None) -> None:
        self.plan = plan or make_plan()
        self.planner_calls = 0
        self.execution_calls = 0
        self.specialist_execution_count = 0
        self.task_calls: list[str] = []
        self.dependency_evidence_seen: dict[str, tuple[str, ...]] = {}

    def create_plan(self, question: str) -> InvestigationPlan:
        self.planner_calls += 1
        if self.plan.question != question.strip():
            return make_plan(question, disposition=self.plan.disposition, tasks=self.plan.tasks if self.plan.disposition is PlanDisposition.READY else None)
        return self.plan

    def validate_plan(self, plan: InvestigationPlan) -> None:
        if not isinstance(plan, InvestigationPlan):
            raise TypeError("plan must be an InvestigationPlan")

    def execute_plan(self, plan: InvestigationPlan) -> InvestigationReport:
        """Return a safe early-exit report for a non-ready plan."""
        self.execution_calls += 1
        if plan.disposition is PlanDisposition.NEEDS_CLARIFICATION:
            status = InvestigationStatus.NEEDS_CLARIFICATION
        elif plan.disposition is PlanDisposition.UNSUPPORTED:
            status = InvestigationStatus.UNSUPPORTED
        else:
            # READY plans must go through individual native nodes.
            raise AssertionError("The outer workflow should not call execute_plan for READY plans.")
        now = datetime.now(UTC).isoformat()
        return InvestigationReport(
            question=plan.question,
            status=status,
            plan=plan,
            started_at_utc=now,
            completed_at_utc=now,
        )

    def execute_planned_task(
        self,
        plan: InvestigationPlan,
        planned_task: PlannedAgentTask,
        *,
        run_id: str,
        task_index: int,
        results_by_task_key: Mapping[str, AgentResult],
        outputs_by_task_key: Mapping[str, tuple[EvidenceReference, ...]],
    ) -> tuple[AgentResult, tuple[EvidenceReference, ...]]:
        """Record dependency visibility and return one evidence item from the task node."""
        assert plan.tasks[task_index - 1] == planned_task
        for dependency_key in planned_task.depends_on:
            if dependency_key not in results_by_task_key:
                raise AssertionError(f"Dependency {dependency_key} has no result.")
        dependency_evidence = tuple(
            evidence
            for dependency_key in planned_task.depends_on
            for evidence in outputs_by_task_key[dependency_key]
        )
        self.dependency_evidence_seen[planned_task.task_key] = tuple(
            item.evidence_id for item in dependency_evidence
        )
        self.specialist_execution_count += 1
        self.task_calls.append(planned_task.task_key)
        evidence = EvidenceReference(
            evidence_id=f"evidence-{planned_task.task_key}",
            source_id=f"source-{planned_task.task_key}",
            title=f"Evidence from {planned_task.task_key}",
            excerpt=f"Evidence content from {planned_task.task_key}.",
            source_uri="https://example.test/source",
            snapshot_id="test-snapshot",
            record_id=f"record-{planned_task.task_key}",
        )
        result = AgentResult(
            task_id=f"{run_id}:{task_index}",
            agent_id=planned_task.agent_id,
            status=AgentStatus.SUCCEEDED,
            summary=f"Completed {planned_task.task_key}",
            evidence=(evidence,),
        )
        return result, (evidence,)

    def report_from_task_results(
        self,
        plan: InvestigationPlan,
        results_by_task_key: Mapping[str, AgentResult],
        *,
        started_at_utc: str,
        completed_at_utc: str | None = None,
    ) -> InvestigationReport:
        expected = {task.task_key for task in plan.tasks}
        if set(results_by_task_key) != expected:
            raise AssertionError("Native graph did not return exactly one result per planned task.")
        results = tuple(results_by_task_key[task.task_key] for task in plan.tasks)
        now = completed_at_utc or datetime.now(UTC).isoformat()
        status = (
            InvestigationStatus.COMPLETED
            if all(result.status is AgentStatus.SUCCEEDED for result in results)
            else InvestigationStatus.PARTIAL
        )
        return InvestigationReport(
            question=plan.question,
            status=status,
            plan=plan,
            results=results,
            started_at_utc=started_at_utc,
            completed_at_utc=now,
        )


def test_plan_only_routes_to_preview_without_specialist_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_langgraph(monkeypatch)
    orchestrator = StubOrchestrator()
    workflow = LangGraphInvestigationWorkflow(orchestrator)  # type: ignore[arg-type]

    report = workflow.investigate("What is eccentricity?", execute=False)

    assert report.status is InvestigationStatus.PLANNED
    assert orchestrator.planner_calls == 1
    assert orchestrator.execution_calls == 0
    assert orchestrator.specialist_execution_count == 0


def test_execution_routes_to_native_task_node_not_legacy_whole_plan_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_langgraph(monkeypatch)
    orchestrator = StubOrchestrator()
    workflow = LangGraphInvestigationWorkflow(orchestrator)  # type: ignore[arg-type]

    report = workflow.investigate("What is eccentricity?", execute=True)

    assert report.status is InvestigationStatus.COMPLETED
    assert orchestrator.planner_calls == 1
    assert orchestrator.execution_calls == 0
    assert orchestrator.specialist_execution_count == 1
    assert orchestrator.task_calls == ["literature-1"]
    assert len(report.results) == 1


def test_clarification_plan_authorizes_no_specialist_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_langgraph(monkeypatch)
    plan = make_plan("Compare q and q", disposition=PlanDisposition.NEEDS_CLARIFICATION)
    orchestrator = StubOrchestrator(plan)
    workflow = LangGraphInvestigationWorkflow(orchestrator)  # type: ignore[arg-type]

    report = workflow.investigate("Compare q and q", execute=True)

    assert report.status is InvestigationStatus.NEEDS_CLARIFICATION
    assert report.plan.tasks == ()
    assert orchestrator.specialist_execution_count == 0
    assert orchestrator.execution_calls == 1


def test_execute_plan_reuses_the_reviewed_plan_without_replanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_langgraph(monkeypatch)
    orchestrator = StubOrchestrator()
    plan = orchestrator.create_plan("What is eccentricity?")
    orchestrator.planner_calls = 0
    workflow = LangGraphInvestigationWorkflow(orchestrator)  # type: ignore[arg-type]

    report = workflow.execute_plan(plan)

    assert report.status is InvestigationStatus.COMPLETED
    assert orchestrator.planner_calls == 0
    assert orchestrator.execution_calls == 0
    assert orchestrator.specialist_execution_count == 1


def test_native_task_graph_hands_only_declared_dependency_evidence_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_langgraph(monkeypatch)
    plan = make_plan(
        tasks=(
            make_task("catalogue-a", agent_id="catalogue_data"),
            make_task("catalogue-b", agent_id="catalogue_data"),
            make_task("calculate-difference", dependencies=("catalogue-a", "catalogue-b"), agent_id="quantitative_analysis"),
            make_task("independent-literature", agent_id="literature_definition"),
        )
    )
    orchestrator = StubOrchestrator(plan)
    graph = build_task_execution_graph(
        orchestrator,  # type: ignore[arg-type]
        plan,
        started_at_utc=datetime.now(UTC).isoformat(),
        run_id="test-run",
    )

    state = graph.invoke(
        {
            "plan": plan,
            "run_id": "test-run",
            "started_at_utc": datetime.now(UTC).isoformat(),
            "results_by_task_key": {},
            "outputs_by_task_key": {},
        }
    )

    report = state["report"]
    assert isinstance(report, InvestigationReport)
    assert report.status is InvestigationStatus.COMPLETED
    assert [result.summary for result in report.results] == [
        "Completed catalogue-a",
        "Completed catalogue-b",
        "Completed calculate-difference",
        "Completed independent-literature",
    ]
    assert set(orchestrator.task_calls) == {
        "catalogue-a",
        "catalogue-b",
        "calculate-difference",
        "independent-literature",
    }
    assert set(orchestrator.dependency_evidence_seen["calculate-difference"]) == {
        "evidence-catalogue-a",
        "evidence-catalogue-b",
    }
    assert orchestrator.dependency_evidence_seen["independent-literature"] == ()


def test_native_graph_refuses_invalid_plan_before_executing_any_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_langgraph(monkeypatch)

    class RejectingOrchestrator(StubOrchestrator):
        def validate_plan(self, _plan: InvestigationPlan) -> None:
            raise ValueError("Plan rejected by test policy.")

    orchestrator = RejectingOrchestrator()
    with pytest.raises(ValueError, match="rejected"):
        build_task_execution_graph(
            orchestrator,  # type: ignore[arg-type]
            orchestrator.plan,
            started_at_utc=datetime.now(UTC).isoformat(),
        )
    assert orchestrator.specialist_execution_count == 0


def test_graph_builder_gives_actionable_error_when_optional_dependency_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if importlib.util.find_spec("langgraph") is not None:
        pytest.skip("The real LangGraph dependency is installed in this environment.")
    monkeypatch.delitem(sys.modules, "langgraph.graph", raising=False)
    monkeypatch.delitem(sys.modules, "langgraph", raising=False)

    with pytest.raises(LangGraphDependencyError, match="requirements-langgraph.txt"):
        build_investigation_graph(StubOrchestrator())  # type: ignore[arg-type]


def test_real_langgraph_integration_when_dependency_is_installed() -> None:
    """Exercise actual multi-node graph execution whenever optional LangGraph is installed."""
    pytest.importorskip("langgraph.graph")
    plan = make_plan(
        tasks=(
            make_task("source-a"),
            make_task("source-b"),
            make_task("join", dependencies=("source-a", "source-b")),
        )
    )
    orchestrator = StubOrchestrator(plan)
    workflow = LangGraphInvestigationWorkflow(orchestrator)  # type: ignore[arg-type]

    preview = workflow.investigate(plan.question, execute=False)
    assert preview.status is InvestigationStatus.PLANNED
    report = workflow.execute_plan(preview.plan)
    assert report.status is InvestigationStatus.COMPLETED
    assert orchestrator.specialist_execution_count == 3
    assert set(orchestrator.dependency_evidence_seen["join"]) == {
        "evidence-source-a",
        "evidence-source-b",
    }


def test_checkpointed_workflow_uses_separate_stable_thread_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer workflow and its task subgraph must not share a checkpoint namespace."""
    from exotrace.agents.checkpointing import task_graph_thread_id

    install_fake_langgraph(monkeypatch)
    plan = make_plan("What is eccentricity?")
    orchestrator = StubOrchestrator(plan)
    saver = object()
    workflow = LangGraphInvestigationWorkflow(
        orchestrator,  # type: ignore[arg-type]
        checkpointer=saver,
    )

    report = workflow.execute_plan(plan, thread_id="test-investigation-thread")

    assert report.status is InvestigationStatus.COMPLETED
    observed = [dict(config or {}) for config in FakeCompiledGraph.invocation_configs]
    assert {"configurable": {"thread_id": "test-investigation-thread"}} in observed
    assert {
        "configurable": {
            "thread_id": task_graph_thread_id("test-investigation-thread")
        }
    } in observed


def test_checkpointed_workflow_requires_a_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent graph state must always have an explicit thread identity."""
    install_fake_langgraph(monkeypatch)
    workflow = LangGraphInvestigationWorkflow(
        StubOrchestrator(),  # type: ignore[arg-type]
        checkpointer=object(),
    )

    with pytest.raises(ValueError, match="thread_id"):
        workflow.investigate("What is eccentricity?")
