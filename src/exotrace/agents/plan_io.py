"""Safe loading of a previously reviewed ExoTrace investigation plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from exotrace.agents.planning import (
    InvestigationPlan,
    PlanDisposition,
    PlannedAgentTask,
)


class SavedPlanError(ValueError):
    """Raised when a saved investigation report cannot safely supply an executable plan."""


def load_plan_from_report_json(
    path: str | Path,
    *,
    expected_question: str,
) -> InvestigationPlan:
    """Load a READY plan from a ``--plan-only`` report and bind it to the supplied question.

    The loader validates report status, question identity, plan shape, and field types. The
    orchestrator must still validate the plan against the current registered agents, tools,
    permissions, context schemas, and task budget immediately before executing it.
    """
    if not isinstance(expected_question, str) or not expected_question.strip():
        raise SavedPlanError("expected_question must be a non-empty string.")

    source_path = Path(path)
    try:
        raw_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SavedPlanError(f"Could not read saved plan report {source_path}: {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SavedPlanError(f"Saved plan report is not valid JSON: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise SavedPlanError("Saved plan report must be a JSON object.")

    if payload.get("status") != "planned":
        raise SavedPlanError(
            "The report must have status 'planned'. Generate a fresh preview with --plan-only; "
            "clarification, unsupported, failed, or already-executed reports cannot be replayed."
        )

    report_question = payload.get("question")
    if not isinstance(report_question, str) or report_question.strip() != expected_question.strip():
        raise SavedPlanError(
            "The saved plan question does not exactly match --query. Use the same question "
            "that generated the preview."
        )

    results = payload.get("results")
    if not isinstance(results, list) or results:
        raise SavedPlanError("A saved plan preview must contain an empty results array.")

    raw_plan = payload.get("plan")
    if not isinstance(raw_plan, Mapping):
        raise SavedPlanError("Saved plan report is missing its plan object.")

    expected_plan_keys = {
        "question",
        "disposition",
        "summary",
        "tasks",
        "clarifying_questions",
        "planner_model",
    }
    if set(raw_plan) != expected_plan_keys:
        raise SavedPlanError(
            "Saved plan contains missing or unexpected plan fields; create a new preview "
            "using the current ExoTrace version."
        )

    plan_question = raw_plan.get("question")
    if not isinstance(plan_question, str) or plan_question.strip() != expected_question.strip():
        raise SavedPlanError("The plan question does not match the report and --query.")

    raw_disposition = raw_plan.get("disposition")
    try:
        disposition = PlanDisposition(raw_disposition)
    except (TypeError, ValueError) as exc:
        raise SavedPlanError(f"Invalid saved plan disposition: {raw_disposition!r}.") from exc
    if disposition is not PlanDisposition.READY:
        raise SavedPlanError(
            "Only a READY plan can be replayed. The saved preview did not authorize executable tasks."
        )

    summary = raw_plan.get("summary")
    planner_model = raw_plan.get("planner_model")
    raw_tasks = raw_plan.get("tasks")
    raw_questions = raw_plan.get("clarifying_questions")
    if not isinstance(summary, str) or not summary.strip():
        raise SavedPlanError("Saved plan summary must be a non-empty string.")
    if not isinstance(planner_model, str) or not planner_model.strip():
        raise SavedPlanError("Saved plan planner_model must be a non-empty string.")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise SavedPlanError("A READY saved plan must contain a non-empty tasks array.")
    if not isinstance(raw_questions, list) or raw_questions:
        raise SavedPlanError("A READY saved plan must have an empty clarifying_questions array.")

    expected_task_keys = {
        "task_key",
        "agent_id",
        "question",
        "objective",
        "required_capabilities",
        "depends_on",
        "context",
    }
    tasks: list[PlannedAgentTask] = []
    for index, raw_task in enumerate(raw_tasks, start=1):
        if not isinstance(raw_task, Mapping):
            raise SavedPlanError(f"Saved task {index} must be a JSON object.")
        if set(raw_task) != expected_task_keys:
            raise SavedPlanError(
                f"Saved task {index} has missing or unexpected fields; create a new preview."
            )

        for field_name in ("task_key", "agent_id", "question", "objective"):
            value = raw_task.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise SavedPlanError(
                    f"Saved task {index} field {field_name!r} must be a non-empty string."
                )

        raw_capabilities = raw_task.get("required_capabilities")
        if not isinstance(raw_capabilities, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw_capabilities
        ):
            raise SavedPlanError(
                f"Saved task {index} required_capabilities must be an array of strings."
            )

        raw_dependencies = raw_task.get("depends_on")
        if not isinstance(raw_dependencies, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw_dependencies
        ):
            raise SavedPlanError(f"Saved task {index} depends_on must be an array of strings.")

        context = raw_task.get("context")
        if not isinstance(context, Mapping):
            raise SavedPlanError(f"Saved task {index} context must be a JSON object.")

        try:
            tasks.append(
                PlannedAgentTask(
                    task_key=raw_task["task_key"],
                    agent_id=raw_task["agent_id"],
                    question=raw_task["question"],
                    objective=raw_task["objective"],
                    required_capabilities=tuple(raw_capabilities),
                    depends_on=tuple(raw_dependencies),
                    context=dict(context),
                )
            )
        except (TypeError, ValueError) as exc:
            raise SavedPlanError(f"Saved task {index} is invalid: {exc}") from exc

    try:
        return InvestigationPlan(
            question=plan_question.strip(),
            disposition=disposition,
            summary=summary,
            tasks=tuple(tasks),
            clarifying_questions=tuple(raw_questions),
            planner_model=planner_model,
        )
    except (TypeError, ValueError) as exc:
        raise SavedPlanError(f"Saved investigation plan is inconsistent: {exc}") from exc
