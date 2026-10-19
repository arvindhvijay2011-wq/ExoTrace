"""Offline tests for the Streamlit-to-CLI service boundary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from exotrace.ui import service
from exotrace.ui.service import (
    InvestigationExecutionError,
    execute_investigation,
    preview_investigation,
)


def _report(*, status: str = "planned", disposition: str = "ready") -> dict[str, Any]:
    return {
        "question": "Compare Kepler-10 radii.",
        "status": status,
        "plan": {
            "disposition": disposition,
            "summary": "Retrieve two records, then calculate a ratio.",
            "tasks": [
                {
                    "task_key": "task-1",
                    "agent_id": "literature_definition",
                    "question": "What does orbital eccentricity mean?",
                    "objective": "Retrieve an official field definition.",
                    "required_capabilities": ["parameter.definition"],
                    "depends_on": [],
                    "context": {"query": "pl_orbeccen"},
                }
            ],
            "clarifying_questions": [],
            "planner_model": "test-model",
        },
        "results": [],
        "started_at_utc": "2026-10-19T00:00:00+00:00",
        "completed_at_utc": "2026-10-19T00:00:00+00:00",
    }


def _mock_process_run(monkeypatch: pytest.MonkeyPatch, *, result_report: dict[str, Any] | None = None):
    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        output_path = Path(kwargs["cwd"]) / command[command.index("--save-json") + 1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result_report or _report()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="CLI output", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    return calls


def test_preview_passes_query_as_one_argument_and_saves_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src/exotrace/agents").mkdir(parents=True)
    (tmp_path / "src/exotrace/agents/investigate.py").write_text("# CLI placeholder", encoding="utf-8")
    calls = _mock_process_run(monkeypatch)

    artifact = preview_investigation(
        'Compare "Kepler-10 b" with Kepler-10 c.',
        project_root=tmp_path,
        planner_output_tokens=5000,
    )

    command = calls[0]["command"]
    assert command[command.index("--query") + 1] == 'Compare "Kepler-10 b" with Kepler-10 c.'
    assert "--plan-only" in command
    assert artifact.report["status"] == "planned"
    assert artifact.report_path.is_file()
    assert calls[0].get("shell", False) is False


def test_execute_uses_saved_plan_without_replanning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src/exotrace/agents").mkdir(parents=True)
    (tmp_path / "src/exotrace/agents/investigate.py").write_text("# CLI placeholder", encoding="utf-8")
    plan_path = tmp_path / "data/manifests/ui_runs/existing_plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(json.dumps(_report()), encoding="utf-8")
    calls = _mock_process_run(monkeypatch, result_report=_report(status="completed"))

    artifact = execute_investigation(
        "Compare Kepler-10 radii.",
        plan_path=plan_path,
        run_id="frontend_test_run",
        project_root=tmp_path,
    )

    command = calls[0]["command"]
    assert "--plan-json" in command
    assert Path("data/manifests/ui_runs/existing_plan.json").as_posix() == command[command.index("--plan-json") + 1]
    assert "--plan-only" not in command
    assert artifact.report["status"] == "completed"


def test_blank_query_is_rejected_before_process_launch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Enter a scientific question"):
        preview_investigation("  ", project_root=tmp_path)


def test_execute_requires_existing_reviewed_plan(tmp_path: Path) -> None:
    (tmp_path / "src/exotrace/agents").mkdir(parents=True)
    (tmp_path / "src/exotrace/agents/investigate.py").write_text("# CLI placeholder", encoding="utf-8")
    with pytest.raises(InvestigationExecutionError, match="Saved investigation plan not found"):
        execute_investigation(
            "A question",
            plan_path=Path("missing_plan.json"),
            run_id="test_run",
            project_root=tmp_path,
        )


def test_child_environment_adds_source_path_without_mutating_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "existing-path")
    original = service.os.environ.get("PYTHONPATH")

    environment = service._make_environment(tmp_path, planner_output_tokens=5000)

    assert str(tmp_path / "src") in environment["PYTHONPATH"]
    assert environment["EXOTRACE_PLANNER_MAX_OUTPUT_TOKENS"] == "5000"
    assert service.os.environ.get("PYTHONPATH") == original


def test_synthesis_runs_separate_cli_and_preserves_top_level_answer_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src/exotrace/agents").mkdir(parents=True)
    (tmp_path / "src/exotrace/agents/synthesis.py").write_text("# CLI placeholder", encoding="utf-8")
    report_path = tmp_path / "data/manifests/ui_runs/frontend_run_result.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps(_report(status="completed")), encoding="utf-8")
    answer_payload = {
        "query": "Compare Kepler-10 radii.",
        "answerable": True,
        "claims": [{"text": "The ratio is supported by the records.", "evidence_ids": ["E1"]}],
        "evidence": [{"evidence_id": "E1", "title": "Catalogue record"}],
        "insufficient_reason": "",
        "markdown": "## Answer",
    }
    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        output_path = Path(kwargs["cwd"]) / command[command.index("--save-json") + 1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(answer_payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="Synthesis output", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    artifact = service.synthesize_investigation(
        report_path,
        run_id="frontend_run",
        project_root=tmp_path,
        environment_overrides={"NEO4J_PASSWORD": "only-child-process"},
    )

    command = calls[0]["command"]
    assert command[1:3] == ["-m", "exotrace.agents.synthesis"]
    assert command[command.index("--report") + 1] == "data/manifests/ui_runs/frontend_run_result.json"
    assert calls[0]["env"]["NEO4J_PASSWORD"] == "only-child-process"
    assert artifact.answer["answerable"] is True
    assert artifact.answer_path.name == "frontend_run_answer.json"


def test_synthesis_rejects_unexpected_report_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src/exotrace/agents").mkdir(parents=True)
    (tmp_path / "src/exotrace/agents/synthesis.py").write_text("# CLI placeholder", encoding="utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(status="completed")), encoding="utf-8")

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        output_path = Path(kwargs["cwd"]) / command[command.index("--save-json") + 1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"answer": {"answerable": True}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    with pytest.raises(InvestigationExecutionError, match="unexpected report shape"):
        service.synthesize_investigation(
            report_path,
            run_id="frontend_run",
            project_root=tmp_path,
        )
