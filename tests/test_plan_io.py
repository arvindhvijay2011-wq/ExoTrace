"""Tests for securely replaying a previously reviewed investigation plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from exotrace.agents.plan_io import SavedPlanError, load_plan_from_report_json
from exotrace.agents.planning import InvestigationPlan, PlanDisposition, PlannedAgentTask


QUESTION = "What does planetary orbital eccentricity describe?"


def ready_plan() -> InvestigationPlan:
    """Create a small reviewed plan without calling the language model."""
    return InvestigationPlan(
        question=QUESTION,
        disposition=PlanDisposition.READY,
        summary="Retrieve the definition from an official reference source.",
        tasks=(
            PlannedAgentTask(
                task_key="define_eccentricity",
                agent_id="literature_definition",
                question=QUESTION,
                objective="Retrieve relevant parameter definition evidence.",
                required_capabilities=(
                    "literature.retrieve",
                    "source.reference_search",
                    "parameter.definition",
                ),
                context={},
            ),
        ),
        clarifying_questions=(),
        planner_model="offline-test-planner",
    )


def write_report(
    path: Path,
    *,
    plan: InvestigationPlan | None = None,
    status: str = "planned",
    results: list[dict[str, Any]] | None = None,
) -> None:
    """Write the same top-level shape used by an ExoTrace InvestigationReport."""
    selected_plan = plan or ready_plan()
    payload = {
        "question": selected_plan.question,
        "status": status,
        "plan": selected_plan.to_dict(),
        "results": [] if results is None else results,
        "started_at_utc": "2026-01-01T00:00:00+00:00",
        "completed_at_utc": "2026-01-01T00:00:00+00:00",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_loads_ready_plan_without_altering_tasks(tmp_path: Path) -> None:
    report_path = tmp_path / "preview.json"
    original = ready_plan()
    write_report(report_path, plan=original)

    loaded = load_plan_from_report_json(report_path, expected_question=QUESTION)

    assert loaded == original
    assert loaded.tasks[0].agent_id == "literature_definition"
    assert loaded.tasks[0].task_key == "define_eccentricity"


def test_rejects_question_mismatch(tmp_path: Path) -> None:
    report_path = tmp_path / "preview.json"
    write_report(report_path)

    with pytest.raises(SavedPlanError, match="does not exactly match"):
        load_plan_from_report_json(
            report_path,
            expected_question="What is orbital eccentricity?",
        )


def test_rejects_report_that_is_not_a_plan_preview(tmp_path: Path) -> None:
    report_path = tmp_path / "completed.json"
    write_report(report_path, status="completed")

    with pytest.raises(SavedPlanError, match="status 'planned'"):
        load_plan_from_report_json(report_path, expected_question=QUESTION)


def test_rejects_saved_report_with_results(tmp_path: Path) -> None:
    report_path = tmp_path / "not-a-preview.json"
    write_report(report_path, results=[{"agent_id": "literature_definition"}])

    with pytest.raises(SavedPlanError, match="empty results array"):
        load_plan_from_report_json(report_path, expected_question=QUESTION)


def test_rejects_non_ready_plan_even_if_report_status_claims_planned(tmp_path: Path) -> None:
    report_path = tmp_path / "inconsistent.json"
    clarification_plan = InvestigationPlan(
        question=QUESTION,
        disposition=PlanDisposition.NEEDS_CLARIFICATION,
        summary="More detail is needed.",
        tasks=(),
        clarifying_questions=("Which context do you want?",),
        planner_model="offline-test-planner",
    )
    write_report(report_path, plan=clarification_plan, status="planned")

    with pytest.raises(SavedPlanError, match="Only a READY plan"):
        load_plan_from_report_json(report_path, expected_question=QUESTION)


def test_rejects_malformed_task_context(tmp_path: Path) -> None:
    report_path = tmp_path / "malformed.json"
    write_report(report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["plan"]["tasks"][0]["context"] = "not-an-object"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SavedPlanError, match="context must be a JSON object"):
        load_plan_from_report_json(report_path, expected_question=QUESTION)


def test_rejects_unexpected_task_fields(tmp_path: Path) -> None:
    report_path = tmp_path / "unexpected-field.json"
    write_report(report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["plan"]["tasks"][0]["execute_arbitrary_code"] = True
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SavedPlanError, match="missing or unexpected fields"):
        load_plan_from_report_json(report_path, expected_question=QUESTION)


def test_rejects_invalid_json(tmp_path: Path) -> None:
    report_path = tmp_path / "bad.json"
    report_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(SavedPlanError, match="not valid JSON"):
        load_plan_from_report_json(report_path, expected_question=QUESTION)
