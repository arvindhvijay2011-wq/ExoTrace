"""Regression tests for plans that must be rejected before specialist execution."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from exotrace.ui.plan_guard import plan_review_issues


QUERY = (
    "Compare the catalogue radii of Kepler-10 b and Kepler-10 c, calculate the radius ratio, "
    "and preserve evidence and snapshot provenance."
)


def _catalogue(project_root: Path) -> None:
    path = project_root / "data" / "processed" / "planets_validated.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pl_name", "hostname", "pl_rade"])
        writer.writeheader()
        writer.writerow({"pl_name": "Kepler-10 b", "hostname": "Kepler-10", "pl_rade": "1.47"})
        writer.writerow({"pl_name": "Kepler-10 c", "hostname": "Kepler-10", "pl_rade": "2.355"})


def _catalogue_task(task_key: str, planet_name: str) -> dict[str, Any]:
    return {
        "task_key": task_key,
        "agent_id": "catalogue_data",
        "question": f"Retrieve the radius for {planet_name}.",
        "objective": f"Retrieve the exact catalogue record for {planet_name}.",
        "depends_on": [],
        "required_capabilities": ["catalogue.lookup", "catalogue.raw_values", "source.provenance"],
        "context": {
            "filters": [{"field": "pl_name", "value": planet_name}],
            "fields": ["pl_name", "hostname", "pl_rade"],
            "match_mode": "exact",
            "limit": 1,
        },
    }


def _valid_report() -> dict[str, Any]:
    b = _catalogue_task("lookup_b", "Kepler-10 b")
    c = _catalogue_task("lookup_c", "Kepler-10 c")
    calculation = {
        "task_key": "ratio_task",
        "agent_id": "quantitative_analysis",
        "question": "Calculate Kepler-10 c divided by Kepler-10 b.",
        "objective": "Calculate the radius ratio.",
        "depends_on": ["lookup_b", "lookup_c"],
        "required_capabilities": ["quantitative.calculate", "quantitative.deterministic", "source.provenance"],
        "context": {
            "calculations": [
                {
                    "calculation_id": "radius_ratio",
                    "operation": "ratio",
                    "operands": [
                        {"source_task_key": "lookup_c", "field": "pl_rade"},
                        {"source_task_key": "lookup_b", "field": "pl_rade"},
                    ],
                }
            ]
        },
    }
    return {
        "question": QUERY,
        "status": "planned",
        "plan": {
            "question": QUERY,
            "disposition": "ready",
            "summary": "Retrieve two radii and calculate the ratio.",
            "tasks": [b, c, calculation],
            "clarifying_questions": [],
            "planner_model": "test-model",
        },
    }


def test_valid_two_planet_ratio_plan_passes_guard(tmp_path: Path) -> None:
    _catalogue(tmp_path)
    assert plan_review_issues(_valid_report(), project_root=tmp_path) == ()


def test_guard_rejects_plan_missing_one_named_planet_and_calculation(tmp_path: Path) -> None:
    _catalogue(tmp_path)
    report = _valid_report()
    report["plan"]["tasks"] = [report["plan"]["tasks"][0]]

    issues = plan_review_issues(report, project_root=tmp_path)

    assert any("Kepler-10 c" in issue and "no catalogue_data task" in issue for issue in issues)
    assert any("no quantitative_analysis task" in issue for issue in issues)


def test_guard_rejects_placeholder_and_unrequested_filters(tmp_path: Path) -> None:
    _catalogue(tmp_path)
    report = _valid_report()
    filters = report["plan"]["tasks"][0]["context"]["filters"]
    filters.extend(
        [
            {"field": "hostname", "value": "Kepler-10"},
            {"field": "sy_snum", "value": "10"},
            {"field": "sy_pnum", "value": "1"},
            {"field": "cb_flag", "value": "null"},
        ]
    )

    issues = plan_review_issues(report, project_root=tmp_path)

    assert any("placeholder value 'null'" in issue for issue in issues)
    assert any("unrequested filter 'hostname'" in issue for issue in issues)
    assert any("unrequested filter 'sy_snum'" in issue for issue in issues)


def test_guard_rejects_calculation_missing_upstream_dependency(tmp_path: Path) -> None:
    _catalogue(tmp_path)
    report = _valid_report()
    report["plan"]["tasks"][2]["depends_on"] = ["lookup_b"]

    issues = plan_review_issues(report, project_root=tmp_path)

    assert any("missing dependencies for lookup_c" in issue for issue in issues)
