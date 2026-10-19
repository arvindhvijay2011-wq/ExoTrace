"""Native LangGraph lifecycle and dependency-aware specialist-task execution for ExoTrace.

Planning remains one explicit graph node. For each READY plan, a compiled execution subgraph is
built with one native LangGraph node per planned specialist task. Dependency edges control when
nodes can run, and reducer-backed state merges their results and provenance-aware evidence.

Specialist execution semantics are shared with the legacy orchestrator through its single-task
boundary. This avoids duplicating tool permissions, context validation, result validation, and
producer tagging while making the task graph itself native LangGraph.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from exotrace.agents.checkpointing import task_graph_thread_id, validate_thread_id
from exotrace.agents.contracts import AgentResult
from exotrace.agents.orchestrator import (
    InvestigationOrchestrator,
    InvestigationReport,
    InvestigationStatus,
    OrchestrationError,
)
from exotrace.agents.planning import InvestigationPlan, PlanDisposition, PlannedAgentTask
from exotrace.contracts import EvidenceReference


class LangGraphDependencyError(ImportError):
    """Raised when LangGraph is selected but the optional dependency is unavailable."""


def _merge_keyed_state(
    current: dict[str, Any] | None,
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge per-task state maps without permitting duplicate task-key writes.

    Different task nodes may finish in the same LangGraph superstep. Each node writes only its
    own task key; duplicate writes indicate an invalid graph or state update and fail closed.
    """
    merged = dict(current or {})
    incoming = dict(update or {})
    collisions = sorted(set(merged) & set(incoming))
    if collisions:
        raise OrchestrationError(
            f"Multiple LangGraph task nodes attempted to write the same key(s): {collisions}."
        )
    merged.update(incoming)
    return merged


class InvestigationGraphState(TypedDict, total=False):
    """State carried through the outer planning and routing graph."""

    question: str
    plan_only: bool
    plan: InvestigationPlan
    report: InvestigationReport
    started_at_utc: str
    checkpoint_thread_id: str


class TaskExecutionGraphState(TypedDict, total=False):
    """State for one plan-specific graph with one node per specialist task."""

    plan: InvestigationPlan
    run_id: str
    started_at_utc: str
    checkpoint_thread_id: str
    results_by_task_key: Annotated[dict[str, AgentResult], _merge_keyed_state]
    outputs_by_task_key: Annotated[
        dict[str, tuple[EvidenceReference, ...]], _merge_keyed_state
    ]
    report: InvestigationReport


def _langgraph_symbols() -> tuple[Any, Any, Any]:
    """Load the optional LangGraph graph API lazily with an actionable error message."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise LangGraphDependencyError(
            "The LangGraph engine requires the optional dependency. Activate ExoTrace's .venv "
            "and run: python -m pip install -r requirements-langgraph.txt"
        ) from exc
    return START, END, StateGraph


def build_task_execution_graph(
    orchestrator: InvestigationOrchestrator,
    plan: InvestigationPlan,
    *,
    started_at_utc: str,
    run_id: str | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Compile one native graph node per planned task, linked by declared dependencies.

    Independent root tasks can execute in the same LangGraph superstep. A dependent task is
    scheduled only after all of its declared predecessors have completed. Failed predecessor
    tasks produce no downstream evidence; the dependent task then records a failure through the
    same structured task boundary used by the legacy executor.
    """
    START, END, StateGraph = _langgraph_symbols()
    orchestrator.validate_plan(plan)
    if plan.disposition is not PlanDisposition.READY:
        raise ValueError("A task execution graph can only be built for a READY plan.")
    if not started_at_utc.strip():
        raise ValueError("started_at_utc must be non-empty.")

    resolved_run_id = run_id or uuid4().hex
    if not resolved_run_id.strip():
        raise ValueError("run_id must be non-empty.")

    task_node_names = {
        task.task_key: f"specialist_task_{index:03d}"
        for index, task in enumerate(plan.tasks, start=1)
    }
    builder = StateGraph(TaskExecutionGraphState)

    for task_index, planned_task in enumerate(plan.tasks, start=1):
        node_name = task_node_names[planned_task.task_key]

        def execute_task_node(
            state: TaskExecutionGraphState,
            *,
            task: PlannedAgentTask = planned_task,
            index: int = task_index,
        ) -> dict[str, Any]:
            """Execute one task using only evidence produced by its declared dependencies."""
            outputs_by_task_key = state.get("outputs_by_task_key", {})
            result, produced_evidence = orchestrator.execute_planned_task(
                plan,
                task,
                run_id=state.get("run_id", resolved_run_id),
                task_index=index,
                results_by_task_key=state.get("results_by_task_key", {}),
                outputs_by_task_key=outputs_by_task_key,
            )
            return {
                "results_by_task_key": {task.task_key: result},
                "outputs_by_task_key": {task.task_key: produced_evidence},
            }

        builder.add_node(node_name, execute_task_node)

    builder.add_node(
        "finalize_task_results",
        lambda state: {
            "report": orchestrator.report_from_task_results(
                plan,
                state.get("results_by_task_key", {}),
                started_at_utc=state.get("started_at_utc", started_at_utc),
            )
        },
    )

    task_keys = {task.task_key for task in plan.tasks}
    dependency_keys = {
        dependency_key
        for task in plan.tasks
        for dependency_key in task.depends_on
    }
    roots = [task for task in plan.tasks if not task.depends_on]
    leaves = [task for task in plan.tasks if task.task_key not in dependency_keys]

    if not roots:
        raise OrchestrationError("The READY plan has no root tasks; dependency graph is invalid.")
    if not leaves:
        raise OrchestrationError("The READY plan has no terminal tasks; dependency graph is invalid.")

    for task in plan.tasks:
        node_name = task_node_names[task.task_key]
        if not task.depends_on:
            builder.add_edge(START, node_name)
            continue
        unknown_dependencies = sorted(set(task.depends_on) - task_keys)
        if unknown_dependencies:
            raise OrchestrationError(
                f"Task {task.task_key!r} has unknown dependencies: {unknown_dependencies}."
            )
        dependency_nodes = [task_node_names[key] for key in task.depends_on]
        if len(dependency_nodes) == 1:
            builder.add_edge(dependency_nodes[0], node_name)
        else:
            # LangGraph's multi-source edge is a join: wait for every declared prerequisite.
            builder.add_edge(dependency_nodes, node_name)

    leaf_node_names = [task_node_names[task.task_key] for task in leaves]
    if len(leaf_node_names) == 1:
        builder.add_edge(leaf_node_names[0], "finalize_task_results")
    else:
        builder.add_edge(leaf_node_names, "finalize_task_results")
    builder.add_edge("finalize_task_results", END)

    if checkpointer is None:
        return builder.compile()
    return builder.compile(checkpointer=checkpointer)


def build_investigation_graph(
    orchestrator: InvestigationOrchestrator,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Build the outer LangGraph for plan creation, preview routing, and task-graph execution."""
    START, END, StateGraph = _langgraph_symbols()

    def create_plan_node(state: InvestigationGraphState) -> dict[str, Any]:
        """Create one plan or accept a previously reviewed plan without replanning."""
        question = state.get("question", "")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("LangGraph investigation state requires a non-empty question.")
        supplied_plan = state.get("plan")
        if supplied_plan is None:
            plan = orchestrator.create_plan(question)
        else:
            if not isinstance(supplied_plan, InvestigationPlan):
                raise TypeError("The supplied plan must be an InvestigationPlan.")
            if supplied_plan.question != question.strip():
                raise ValueError("The supplied plan does not match the investigation question.")
            plan = supplied_plan
            orchestrator.validate_plan(plan)
        started = state.get("started_at_utc") or datetime.now(UTC).isoformat()
        return {"plan": plan, "started_at_utc": started}

    def route_after_planning(state: InvestigationGraphState) -> str:
        """Route plan preview requests separately from plan execution."""
        return "preview" if state.get("plan_only", False) else "execute"

    def preview_node(state: InvestigationGraphState) -> dict[str, Any]:
        """Create a report from the plan without executing specialist tasks."""
        plan = state.get("plan")
        if not isinstance(plan, InvestigationPlan):
            raise TypeError("The planning node did not produce an InvestigationPlan.")
        if plan.disposition is PlanDisposition.READY:
            status = InvestigationStatus.PLANNED
        elif plan.disposition is PlanDisposition.NEEDS_CLARIFICATION:
            status = InvestigationStatus.NEEDS_CLARIFICATION
        else:
            status = InvestigationStatus.UNSUPPORTED
        now = datetime.now(UTC).isoformat()
        return {
            "report": InvestigationReport(
                question=plan.question,
                status=status,
                plan=plan,
                started_at_utc=state.get("started_at_utc") or now,
                completed_at_utc=now,
            )
        }

    def execute_node(state: InvestigationGraphState) -> dict[str, Any]:
        """Run each specialist task as a node in a plan-specific native LangGraph subgraph."""
        plan = state.get("plan")
        if not isinstance(plan, InvestigationPlan):
            raise TypeError("The planning node did not produce an InvestigationPlan.")
        if plan.disposition is not PlanDisposition.READY:
            # Delegate non-ready report semantics to the existing safe early-exit path; it
            # returns without invoking any specialist.
            return {"report": orchestrator.execute_plan(plan)}

        started = state.get("started_at_utc") or datetime.now(UTC).isoformat()
        checkpoint_thread = state.get("checkpoint_thread_id")
        if checkpointer is not None and not checkpoint_thread:
            raise ValueError("Checkpointed LangGraph execution requires checkpoint_thread_id.")
        task_graph = build_task_execution_graph(
            orchestrator,
            plan,
            started_at_utc=started,
            checkpointer=checkpointer,
        )
        task_state = {
            "plan": plan,
            "run_id": uuid4().hex,
            "started_at_utc": started,
            "results_by_task_key": {},
            "outputs_by_task_key": {},
        }
        if checkpointer is not None:
            task_state["checkpoint_thread_id"] = checkpoint_thread
            task_config = {
                "configurable": {"thread_id": task_graph_thread_id(checkpoint_thread)}
            }
            result = task_graph.invoke(task_state, config=task_config)
        else:
            result = task_graph.invoke(task_state)
        report = result.get("report") if isinstance(result, dict) else None
        if not isinstance(report, InvestigationReport):
            raise TypeError("LangGraph specialist-task graph ended without an InvestigationReport.")
        return {"report": report}

    builder = StateGraph(InvestigationGraphState)
    builder.add_node("create_plan", create_plan_node)
    builder.add_node("preview_plan", preview_node)
    builder.add_node("execute_task_graph", execute_node)
    builder.add_edge(START, "create_plan")
    builder.add_conditional_edges(
        "create_plan",
        route_after_planning,
        {"preview": "preview_plan", "execute": "execute_task_graph"},
    )
    builder.add_edge("preview_plan", END)
    builder.add_edge("execute_task_graph", END)
    if checkpointer is None:
        return builder.compile()
    return builder.compile(checkpointer=checkpointer)


class LangGraphInvestigationWorkflow:
    """Run planning, preview, and individual specialist tasks through native LangGraph nodes."""

    def __init__(
        self,
        orchestrator: InvestigationOrchestrator,
        *,
        checkpointer: Any | None = None,
    ) -> None:
        """Compile the outer graph, optionally with persistent checkpoint storage."""
        self._checkpointer = checkpointer
        self._graph = build_investigation_graph(
            orchestrator, checkpointer=checkpointer
        )

    def investigate(
        self,
        question: str,
        *,
        execute: bool = True,
        thread_id: str | None = None,
    ) -> InvestigationReport:
        """Create a single plan, then preview it or execute its specialist-task graph."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string.")
        state: dict[str, Any] = {
            "question": question.strip(),
            "plan_only": not execute,
            "started_at_utc": datetime.now(UTC).isoformat(),
        }
        config = self._invoke_config(thread_id)
        if self._checkpointer is not None:
            state["checkpoint_thread_id"] = thread_id
            result = self._graph.invoke(state, config=config)
        else:
            if thread_id is not None:
                raise ValueError("thread_id may only be supplied when checkpointing is enabled.")
            result = self._graph.invoke(state)
        return self._require_report(result)

    def execute_plan(
        self,
        plan: InvestigationPlan,
        *,
        thread_id: str | None = None,
    ) -> InvestigationReport:
        """Execute a previously reviewed plan without asking the planner to replan."""
        if not isinstance(plan, InvestigationPlan):
            raise TypeError("plan must be an InvestigationPlan.")
        state: dict[str, Any] = {
            "question": plan.question,
            "plan": plan,
            "plan_only": False,
            "started_at_utc": datetime.now(UTC).isoformat(),
        }
        config = self._invoke_config(thread_id)
        if self._checkpointer is not None:
            state["checkpoint_thread_id"] = thread_id
            result = self._graph.invoke(state, config=config)
        else:
            if thread_id is not None:
                raise ValueError("thread_id may only be supplied when checkpointing is enabled.")
            result = self._graph.invoke(state)
        return self._require_report(result)

    def _invoke_config(self, thread_id: str | None) -> dict[str, Any] | None:
        """Build the required LangGraph thread configuration when checkpointing is active."""
        if self._checkpointer is None:
            if thread_id is not None:
                raise ValueError("thread_id may only be supplied when checkpointing is enabled.")
            return None
        normalized_thread_id = validate_thread_id(thread_id or "")
        return {"configurable": {"thread_id": normalized_thread_id}}

    @staticmethod
    def _require_report(result: Any) -> InvestigationReport:
        """Reject malformed graph output rather than silently returning a partial value."""
        if not isinstance(result, dict):
            raise TypeError("LangGraph returned a non-dictionary workflow state.")
        report = result.get("report")
        if not isinstance(report, InvestigationReport):
            raise TypeError("LangGraph finished without an InvestigationReport.")
        return report
