"""Real SQLite/StateGraph persistence smoke test, skipped when optional extras are absent."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pytest

from exotrace.agents.checkpointing import open_sqlite_checkpointer
from exotrace.agents.planning import InvestigationPlan, PlanDisposition, PlannedAgentTask


class PersistenceState(TypedDict, total=False):
    question: str
    plan: InvestigationPlan


def make_plan(question: str) -> InvestigationPlan:
    """Build a representative typed ExoTrace plan for serializer round-trip testing."""
    return InvestigationPlan(
        question=question,
        disposition=PlanDisposition.READY,
        summary="Persist this plan for a resume test.",
        tasks=(
            PlannedAgentTask(
                agent_id="literature_definition",
                question=question,
                objective="Retrieve a definition.",
                required_capabilities=("literature.retrieve",),
                task_key="definition-task",
            ),
        ),
        planner_model="checkpoint-test",
    )


def test_sqlite_checkpointer_restores_allowlisted_plan_across_connections(
    tmp_path: Path,
) -> None:
    """An ExoTrace dataclass should survive a real close/reopen checkpoint round trip."""
    pytest.importorskip("langgraph.graph")
    pytest.importorskip("langgraph.checkpoint.sqlite")
    from langgraph.graph import END, START, StateGraph

    question = "What is orbital eccentricity?"
    plan = make_plan(question)
    database_path = tmp_path / "checkpoints.sqlite"
    config = {"configurable": {"thread_id": "checkpoint-round-trip"}}

    builder = StateGraph(PersistenceState)
    builder.add_node("retain_plan", lambda state: {"plan": state["plan"]})
    builder.add_edge(START, "retain_plan")
    builder.add_edge("retain_plan", END)

    with open_sqlite_checkpointer(database_path) as checkpointer:
        graph = builder.compile(checkpointer=checkpointer)
        result = graph.invoke({"question": question, "plan": plan}, config)
        assert result["plan"] == plan

    with open_sqlite_checkpointer(database_path) as checkpointer:
        snapshot = checkpointer.get_tuple(config)
        assert snapshot is not None
        values = snapshot.checkpoint["channel_values"]
        restored_plan = values["plan"]
        assert isinstance(restored_plan, InvestigationPlan)
        assert restored_plan.question == question
        assert restored_plan.tasks[0].task_key == "definition-task"
