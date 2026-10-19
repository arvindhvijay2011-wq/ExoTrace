"""Safe subprocess bridge from Streamlit to the validated ExoTrace CLI.

The UI does not duplicate orchestration, planning, specialist execution, or scientific
calculation logic. It launches the existing CLI with an argument list (never a shell string),
then loads the CLI's JSON report for display and local history.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from exotrace.ui.plan_guard import plan_review_issues

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UI_RUNS_DIRECTORY = Path("data/manifests/ui_runs")
DEFAULT_TIMEOUT_SECONDS = 900


class InvestigationExecutionError(RuntimeError):
    """A CLI investigation failed or did not produce a readable report."""

    def __init__(
        self,
        message: str,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@dataclass(frozen=True, slots=True)
class InvestigationArtifact:
    """An investigation report and its safe-to-display execution metadata."""

    run_id: str
    report_path: Path
    report: dict[str, Any]
    stdout: str = ""
    stderr: str = ""
    project_root: Path = PROJECT_ROOT

    @property
    def relative_report_path(self) -> str:
        """Return the report path relative to this artifact's project root when possible."""
        try:
            return str(self.report_path.relative_to(self.project_root))
        except ValueError:
            return str(self.report_path)


@dataclass(frozen=True, slots=True)
class SynthesisArtifact:
    """A final grounded answer and its supporting claim-level evidence ledger."""

    run_id: str
    answer_path: Path
    answer: dict[str, Any]
    stdout: str = ""
    stderr: str = ""


def _validate_inputs(
    query: str,
    *,
    max_agent_tasks: int,
    device: str,
    planner_output_tokens: int,
) -> str:
    """Validate UI settings before launching the backend process."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Enter a scientific question before continuing.")
    if isinstance(max_agent_tasks, bool) or not 1 <= max_agent_tasks <= 20:
        raise ValueError("Maximum specialist tasks must be between 1 and 20.")
    if device not in {"cpu", "cuda"}:
        raise ValueError("Embedding device must be 'cpu' or 'cuda'.")
    if isinstance(planner_output_tokens, bool) or not 1000 <= planner_output_tokens <= 20000:
        raise ValueError("Planner output budget must be between 1,000 and 20,000 tokens.")
    return query.strip()


def _make_run_id() -> str:
    """Create a timestamped, filesystem-safe identifier for one UI run."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{uuid4().hex[:8]}"


def _make_environment(
    project_root: Path,
    *,
    planner_output_tokens: int,
    environment_overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a child-process environment without mutating the Streamlit process."""
    environment = os.environ.copy()
    source_path = str(project_root / "src")
    existing_python_path = environment.get("PYTHONPATH", "")
    python_entries = [item for item in existing_python_path.split(os.pathsep) if item]
    if source_path not in python_entries:
        python_entries.insert(0, source_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_entries)
    environment["EXOTRACE_PLANNER_MAX_OUTPUT_TOKENS"] = str(planner_output_tokens)
    if environment_overrides:
        for key, value in environment_overrides.items():
            if not isinstance(key, str) or not key or not isinstance(value, str):
                raise ValueError("Environment overrides must be non-empty string keys and values.")
            if "\x00" in key or "\x00" in value or "=" in key:
                raise ValueError("Invalid environment override.")
            environment[key] = value

    # The parent decodes captured CLI output as UTF-8. Force the child Python process
    # to encode stdout/stderr the same way so Windows locale code pages cannot fail
    # when a source excerpt or generated answer contains Unicode characters.
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _read_report(report_path: Path) -> dict[str, Any]:
    """Read and minimally validate an ExoTrace investigation report."""
    if not report_path.is_file():
        raise InvestigationExecutionError(
            f"The ExoTrace CLI did not create the expected report: {report_path}"
        )
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvestigationExecutionError(
            f"The investigation report could not be read as JSON: {report_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise InvestigationExecutionError("The investigation report must be a JSON object.")
    if not isinstance(payload.get("status"), str) or not isinstance(payload.get("plan"), dict):
        raise InvestigationExecutionError(
            "The investigation report is missing its status or plan object."
        )
    return payload


def _invoke_cli(
    *,
    query: str,
    action: str,
    run_id: str,
    project_root: Path,
    engine: str,
    max_agent_tasks: int,
    device: str,
    planner_output_tokens: int,
    plan_path: Path | None = None,
    environment_overrides: Mapping[str, str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> InvestigationArtifact:
    """Run the existing CLI with safe argument boundaries and a per-run report file."""
    if engine not in {"legacy", "langgraph"}:
        raise ValueError("Workflow engine must be 'legacy' or 'langgraph'.")
    if action not in {"preview", "execute"}:
        raise ValueError("Action must be 'preview' or 'execute'.")
    if timeout_seconds < 1:
        raise ValueError("Timeout must be a positive number of seconds.")

    normalized_query = _validate_inputs(
        query,
        max_agent_tasks=max_agent_tasks,
        device=device,
        planner_output_tokens=planner_output_tokens,
    )
    project_root = project_root.resolve()
    cli_module = project_root / "src" / "exotrace" / "agents" / "investigate.py"
    if not cli_module.is_file():
        raise InvestigationExecutionError(
            f"ExoTrace source was not found under the selected workspace: {project_root}"
        )
    if action == "execute" and plan_path is None:
        raise ValueError("Executing an investigation requires a previously reviewed plan path.")
    if plan_path is not None:
        resolved_plan = plan_path if plan_path.is_absolute() else project_root / plan_path
        if not resolved_plan.is_file():
            raise InvestigationExecutionError(f"Saved investigation plan not found: {resolved_plan}")

    runs_directory = project_root / UI_RUNS_DIRECTORY
    runs_directory.mkdir(parents=True, exist_ok=True)
    suffix = "plan" if action == "preview" else "result"
    relative_report_path = UI_RUNS_DIRECTORY / f"{run_id}_{suffix}.json"
    report_path = project_root / relative_report_path

    command = [
        sys.executable,
        "-m",
        "exotrace.agents.investigate",
        "--engine",
        engine,
        "--device",
        device,
        "--max-agent-tasks",
        str(max_agent_tasks),
        "--query",
        normalized_query,
        "--save-json",
        relative_report_path.as_posix(),
    ]
    if action == "preview":
        command.append("--plan-only")
    else:
        assert plan_path is not None
        resolved_plan = plan_path if plan_path.is_absolute() else project_root / plan_path
        try:
            cli_plan_path = resolved_plan.relative_to(project_root)
        except ValueError:
            cli_plan_path = resolved_plan
        command.extend(["--plan-json", cli_plan_path.as_posix()])

    environment = _make_environment(
        project_root,
        planner_output_tokens=planner_output_tokens,
        environment_overrides=environment_overrides,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        raise InvestigationExecutionError(
            f"ExoTrace exceeded the {timeout_seconds}-second execution limit.",
            stdout=stdout,
            stderr=stderr,
        ) from exc
    except OSError as exc:
        raise InvestigationExecutionError(
            f"Could not launch the ExoTrace CLI: {exc}"
        ) from exc

    if completed.returncode != 0:
        raise InvestigationExecutionError(
            f"ExoTrace CLI exited with code {completed.returncode}.",
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
    report = _read_report(report_path)
    return InvestigationArtifact(
        run_id=run_id,
        report_path=report_path,
        report=report,
        stdout=completed.stdout,
        stderr=completed.stderr,
        project_root=project_root,
    )


def preview_investigation(
    query: str,
    *,
    project_root: Path = PROJECT_ROOT,
    engine: str = "langgraph",
    max_agent_tasks: int = 5,
    device: str = "cpu",
    planner_output_tokens: int = 5000,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> InvestigationArtifact:
    """Generate a plan without executing any specialist tasks."""
    run_id = _make_run_id()
    return _invoke_cli(
        query=query,
        action="preview",
        run_id=run_id,
        project_root=project_root,
        engine=engine,
        max_agent_tasks=max_agent_tasks,
        device=device,
        planner_output_tokens=planner_output_tokens,
        timeout_seconds=timeout_seconds,
    )


def execute_investigation(
    query: str,
    *,
    plan_path: Path,
    run_id: str,
    project_root: Path = PROJECT_ROOT,
    engine: str = "langgraph",
    max_agent_tasks: int = 5,
    device: str = "cpu",
    planner_output_tokens: int = 5000,
    environment_overrides: Mapping[str, str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> InvestigationArtifact:
    """Execute a user-reviewed saved plan after the CLI revalidates it."""
    if not run_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in run_id):
        raise ValueError("run_id contains unsupported characters.")

    # Fail closed before launching any specialist. The Streamlit button is not a security or
    # quality boundary by itself; the service re-reads the saved plan and independently checks
    # explicit catalogue entities, filter hygiene, and calculation dependency coverage.
    project_root = project_root.resolve()
    resolved_plan = plan_path if plan_path.is_absolute() else project_root / plan_path
    if not resolved_plan.is_file():
        raise InvestigationExecutionError(f"Saved investigation plan not found: {resolved_plan}")
    try:
        saved_plan_report = json.loads(resolved_plan.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvestigationExecutionError(
            f"The reviewed plan could not be read as JSON: {resolved_plan}"
        ) from exc
    issues = plan_review_issues(saved_plan_report, project_root=project_root)
    if issues:
        message = "Refusing to execute this plan because pre-execution validation failed:\n- " + "\n- ".join(issues)
        raise ValueError(message)

    return _invoke_cli(
        query=query,
        action="execute",
        run_id=run_id,
        project_root=project_root,
        engine=engine,
        max_agent_tasks=max_agent_tasks,
        device=device,
        planner_output_tokens=planner_output_tokens,
        plan_path=plan_path,
        environment_overrides=environment_overrides,
        timeout_seconds=timeout_seconds,
    )


def effective_settings(project_root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Read ExoTrace's existing environment/.env settings without displaying values."""
    from exotrace.answering.grounded_answer import _load_local_settings

    return _load_local_settings(project_root)


def workspace_readiness(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Return non-secret configuration and data-asset availability for the UI sidebar."""
    settings = effective_settings(project_root)
    required_assets = {
        "Validated catalogue": project_root / "data/processed/planets_validated.csv",
        "Vector corpus": project_root / "data/processed/vector_corpus.jsonl",
        "FAISS index": project_root / "data/processed/vector_index/exotrace.faiss",
    }
    return {
        "assets": {name: path.is_file() for name, path in required_assets.items()},
        "openai_key_configured": bool(settings.get("OPENAI_API_KEY", "").strip()),
        "model_configured": bool(
            (settings.get("EXOTRACE_PLANNER_MODEL") or settings.get("EXOTRACE_LLM_MODEL", "")).strip()
        ),
        "neo4j_password_configured": bool(settings.get("NEO4J_PASSWORD", "").strip()),
        "neo4j_uri_configured": bool(settings.get("NEO4J_URI", "").strip()),
    }


def list_saved_reports(project_root: Path = PROJECT_ROOT, *, limit: int = 20) -> list[Path]:
    """Return newest completed result reports from the app's dedicated history directory."""
    if isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer.")
    directory = project_root / UI_RUNS_DIRECTORY
    if not directory.is_dir():
        return []
    return sorted(
        directory.glob("*_result.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit]


def synthesize_investigation(
    investigation_report_path: Path,
    *,
    run_id: str,
    project_root: Path = PROJECT_ROOT,
    planner_output_tokens: int = 5000,
    environment_overrides: Mapping[str, str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> SynthesisArtifact:
    """Run the existing Answer Synthesis Agent on a completed investigation report.

    Synthesis is kept as a distinct backend command. Its output contains validated citation IDs
    and the exact evidence pack used to generate the final response.
    """
    if not run_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in run_id):
        raise ValueError("run_id contains unsupported characters.")
    if isinstance(planner_output_tokens, bool) or not 1000 <= planner_output_tokens <= 20000:
        raise ValueError("Planner output budget must be between 1,000 and 20,000 tokens.")
    if timeout_seconds < 1:
        raise ValueError("Timeout must be a positive number of seconds.")

    project_root = project_root.resolve()
    source_module = project_root / "src" / "exotrace" / "agents" / "synthesis.py"
    if not source_module.is_file():
        raise InvestigationExecutionError(
            f"Answer Synthesis Agent source was not found under the selected workspace: {project_root}"
        )
    report_path = (
        investigation_report_path
        if investigation_report_path.is_absolute()
        else project_root / investigation_report_path
    ).resolve()
    if not report_path.is_file():
        raise InvestigationExecutionError(f"Investigation report not found: {report_path}")

    output_path = project_root / UI_RUNS_DIRECTORY / f"{run_id}_answer.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        relative_report = report_path.relative_to(project_root)
    except ValueError:
        relative_report = report_path

    command = [
        sys.executable,
        "-m",
        "exotrace.agents.synthesis",
        "--report",
        relative_report.as_posix(),
        "--save-json",
        output_path.relative_to(project_root).as_posix(),
    ]
    environment = _make_environment(
        project_root,
        planner_output_tokens=planner_output_tokens,
        environment_overrides=environment_overrides,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        raise InvestigationExecutionError(
            f"Answer synthesis exceeded the {timeout_seconds}-second execution limit.",
            stdout=stdout,
            stderr=stderr,
        ) from exc
    except OSError as exc:
        raise InvestigationExecutionError(
            f"Could not launch the Answer Synthesis Agent: {exc}"
        ) from exc

    if completed.returncode != 0:
        raise InvestigationExecutionError(
            f"Answer Synthesis Agent exited with code {completed.returncode}.",
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
    if not output_path.is_file():
        raise InvestigationExecutionError(
            f"The Answer Synthesis Agent did not create the expected answer file: {output_path}",
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    try:
        answer_payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvestigationExecutionError(
            f"The synthesized answer could not be read as JSON: {output_path}",
            stdout=completed.stdout,
            stderr=completed.stderr,
        ) from exc
    if (
        not isinstance(answer_payload, dict)
        or not isinstance(answer_payload.get("answerable"), bool)
        or not isinstance(answer_payload.get("claims"), list)
        or not isinstance(answer_payload.get("evidence"), list)
    ):
        raise InvestigationExecutionError(
            "The Answer Synthesis Agent returned an unexpected report shape.",
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    return SynthesisArtifact(
        run_id=run_id,
        answer_path=output_path,
        answer=answer_payload,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
