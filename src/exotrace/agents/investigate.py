"""Run one planned ExoTrace multi-specialist investigation from the command line.

This command plans and gathers structured evidence. It does not synthesize a final scientific
answer; that responsibility belongs to a later, separate Answer Synthesis Agent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from uuid import uuid4
from getpass import getpass
from pathlib import Path
from typing import Any

from exotrace.agents.assembly import build_specialist_layer
from exotrace.agents.checkpointing import (
    ensure_fresh_thread,
    load_resumable_plan,
    open_sqlite_checkpointer,
    task_graph_thread_id,
    validate_thread_id,
)
from exotrace.agents.plan_io import load_plan_from_report_json
from exotrace.agents.planet_identifier_resolution import CataloguePlanetIdentifierResolver
from exotrace.agents.orchestrator import (
    InvestigationOrchestrator,
    InvestigationReport,
    InvestigationStatus,
    OrchestratorConfig,
)
from exotrace.agents.planning import (
    OpenAIResponsesTaskPlanner,
    PlanDisposition,
    PlannerError,
)
from exotrace.answering.grounded_answer import _load_local_settings
from exotrace.tools.catalogue_lookup import CatalogueRecordLookupTool
from exotrace.tools.graph_investigation import GraphInvestigationConfig
from exotrace.vector.build_index import PROJECT_ROOT
from exotrace.vector.retrieve import HybridTextRetriever


def render_investigation_report(
    report: InvestigationReport,
    orchestrator: InvestigationOrchestrator,
) -> str:
    """Render planned specialist tasks and returned findings without inventing synthesis."""
    lines = [
        "# ExoTrace investigation report",
        "",
        f"**Status:** `{report.status.value}`",
        f"**Question:** {report.question}",
        "",
        f"**Plan:** {report.plan.summary}",
        "",
        "## Planned specialist tasks",
        "",
    ]
    if report.plan.tasks:
        for index, task in enumerate(report.plan.tasks, start=1):
            descriptor = orchestrator.agent_descriptor(task.agent_id)
            lines.extend(
                [
                    f"{index}. **{descriptor.name}** (`{descriptor.agent_id}`)",
                    f"   - Task key: `{task.task_key}`",
                    f"   - Objective: {task.objective}",
                    f"   - Required capabilities: {', '.join(task.required_capabilities)}",
                    *(
                        [f"   - Depends on: {', '.join(task.depends_on)}"]
                        if task.depends_on
                        else []
                    ),
                ]
            )
    else:
        lines.append("No specialist tasks were authorized by the planner.")

    if report.plan.clarifying_questions:
        lines.extend(["", "## Clarification needed", ""])
        lines.extend(f"- {question}" for question in report.plan.clarifying_questions)

    if report.results:
        lines.extend(["", "## Specialist results", ""])
        for result in report.results:
            lines.extend(
                [
                    f"### {result.agent_id} · `{result.status.value}`",
                    "",
                    result.summary,
                    "",
                ]
            )
            if result.findings:
                for finding in result.findings:
                    refs = " ".join(f"[{item}]" for item in finding.evidence_ids)
                    lines.append(f"- {finding.statement} {refs}".rstrip())
                lines.append("")
            if result.evidence:
                lines.append("**Evidence provenance**")
                for evidence in result.evidence:
                    source = f" ({evidence.source_uri})" if evidence.source_uri else ""
                    record = f" · record `{evidence.record_id}`" if evidence.record_id else ""
                    snapshot = (
                        f" · snapshot `{evidence.snapshot_id}`"
                        if evidence.snapshot_id
                        else ""
                    )
                    lines.append(
                        f"- `{evidence.evidence_id}` · {evidence.title}{source}{record}{snapshot}"
                    )
                lines.append("")
            if result.gaps:
                lines.append("**Gaps**")
                lines.extend(f"- {gap}" for gap in result.gaps)
                lines.append("")
            if result.error_message:
                lines.append(f"**Execution note:** {result.error_message}")
                lines.append("")

    lines.extend(
        [
            "---",
            "This is a structured investigation report, not the final synthesized "
            "scientific answer.",
        ]
    )
    return "\n".join(lines).strip()


def _create_graph_driver(
    settings: dict[str, str],
    *,
    password_override: str | None = None,
) -> Any:
    """Create a Neo4j driver without opening a session or printing credentials."""
    from neo4j import GraphDatabase

    uri = settings.get("NEO4J_URI", "neo4j://127.0.0.1:7687").strip()
    username = settings.get("NEO4J_USERNAME", "neo4j").strip()
    password = (password_override or settings.get("NEO4J_PASSWORD", "")).strip()
    if password:
        return GraphDatabase.driver(uri, auth=(username, password))
    # The driver is not contacted until a selected graph task executes. If that happens,
    # the CLI detects the tool's declared credential requirement and prompts before running.
    return GraphDatabase.driver(uri)


def _build_orchestrator(
    *,
    retriever: HybridTextRetriever,
    graph_driver: Any,
    planner: OpenAIResponsesTaskPlanner,
    database: str,
    max_agent_tasks: int,
) -> InvestigationOrchestrator:
    """Build live specialists and tools around existing indexes and graph data."""
    agents, tools = build_specialist_layer(
        retriever,
        graph_driver,
        graph_config=GraphInvestigationConfig(database=database),
    )
    catalogue_tool = tools.get(CatalogueRecordLookupTool.TOOL_ID)
    if not isinstance(catalogue_tool, CatalogueRecordLookupTool):
        raise TypeError("The registered catalogue lookup tool is not the validated catalogue tool.")
    identifier_resolver = CataloguePlanetIdentifierResolver(
        catalogue_tool.planet_host_identities,
        agent_descriptors=agents.descriptors(),
        include_context_sources=True,
        max_agent_tasks=max_agent_tasks,
    )
    return InvestigationOrchestrator(
        agent_registry=agents,
        tool_registry=tools,
        planner=planner,
        config=OrchestratorConfig(max_agent_tasks=max_agent_tasks),
        plan_context_resolver=identifier_resolver.resolve_plan,
    )


def main(argv: list[str] | None = None) -> int:
    """Run one bounded investigation using the legacy or optional LangGraph engine."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Scientific question to investigate.")
    parser.add_argument(
        "--engine",
        choices=("legacy", "langgraph"),
        default="legacy",
        help=(
            "Workflow engine. 'legacy' remains the default fallback; select 'langgraph' "
            "to exercise the new StateGraph lifecycle."
        ),
    )
    parser.add_argument(
        "--device", choices=("cpu", "cuda"), default="cpu", help="Embedding inference device."
    )
    parser.add_argument(
        "--max-agent-tasks",
        type=int,
        default=None,
        help="Override EXOTRACE_MAX_AGENT_TASKS for this run.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Ask the planner for a plan but do not execute specialists.",
    )
    parser.add_argument(
        "--plan-json",
        type=Path,
        help=(
            "Execute the exact READY plan from a previously saved --plan-only report. "
            "The --query must match the saved question; this bypasses a new planner call."
        ),
    )
    parser.add_argument(
        "--save-json",
        type=Path,
        help="Optional path for the full plan, findings, and evidence provenance JSON.",
    )
    parser.add_argument(
        "--checkpoint-db",
        type=Path,
        help=(
            "Optional SQLite database for persistent LangGraph checkpoints. "
            "Requires --engine langgraph and cannot be used with --plan-only."
        ),
    )
    parser.add_argument(
        "--thread-id",
        help=(
            "Checkpoint thread ID. Use the same value with --resume after an interrupted run; "
            "omit it to generate a new ID. Requires --checkpoint-db."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an interrupted checkpointed LangGraph run using the existing plan and state. "
            "Requires --checkpoint-db and --thread-id."
        ),
    )
    args = parser.parse_args(argv)
    if args.max_agent_tasks is not None and args.max_agent_tasks < 1:
        parser.error("--max-agent-tasks must be at least 1")
    if args.plan_only and args.plan_json is not None:
        parser.error("--plan-json cannot be combined with --plan-only")
    if args.checkpoint_db is not None and args.engine != "langgraph":
        parser.error("--checkpoint-db requires --engine langgraph")
    if args.thread_id is not None and args.checkpoint_db is None:
        parser.error("--thread-id requires --checkpoint-db")
    if args.resume and (args.checkpoint_db is None or args.thread_id is None):
        parser.error("--resume requires both --checkpoint-db and --thread-id")
    if args.resume and (args.plan_only or args.plan_json is not None):
        parser.error("--resume cannot be combined with --plan-only or --plan-json")
    if args.checkpoint_db is not None and args.plan_only:
        parser.error(
            "--checkpoint-db is for execution runs. Save a preview without checkpointing, "
            "then execute it with --plan-json and --checkpoint-db."
        )

    graph_driver: Any | None = None
    checkpoint_context: Any | None = None
    checkpointer: Any | None = None
    checkpoint_thread_id: str | None = None
    try:
        saved_plan = None
        if args.checkpoint_db is not None:
            checkpoint_path = args.checkpoint_db
            if not checkpoint_path.is_absolute():
                checkpoint_path = PROJECT_ROOT / checkpoint_path
            checkpoint_manager = open_sqlite_checkpointer(checkpoint_path)
            checkpointer = checkpoint_manager.__enter__()
            checkpoint_context = checkpoint_manager
            if args.resume:
                checkpoint_thread_id = validate_thread_id(args.thread_id or "")
                saved_plan = load_resumable_plan(
                    checkpointer,
                    checkpoint_thread_id,
                    expected_question=args.query,
                )
            else:
                checkpoint_thread_id = validate_thread_id(args.thread_id or uuid4().hex)
                ensure_fresh_thread(checkpointer, checkpoint_thread_id)
                ensure_fresh_thread(checkpointer, task_graph_thread_id(checkpoint_thread_id))
            print(f"LangGraph checkpoint database: {checkpoint_path}")
            print(f"Checkpoint thread ID: {checkpoint_thread_id}")
            if args.resume:
                print("Resuming the interrupted checkpointed investigation.")
        if args.plan_json is not None:
            plan_path = args.plan_json
            if not plan_path.is_absolute():
                plan_path = PROJECT_ROOT / plan_path
            saved_plan = load_plan_from_report_json(
                plan_path, expected_question=args.query
            )

        settings = _load_local_settings(PROJECT_ROOT)
        planner = OpenAIResponsesTaskPlanner.from_environment(PROJECT_ROOT)
        max_tasks = args.max_agent_tasks or int(settings.get("EXOTRACE_MAX_AGENT_TASKS", "5"))
        if max_tasks < 1:
            raise ValueError("EXOTRACE_MAX_AGENT_TASKS must be at least 1.")
        database = settings.get("NEO4J_DATABASE", "exotrace").strip()
        retriever = HybridTextRetriever(device=args.device)
        graph_driver = _create_graph_driver(settings)
        orchestrator = _build_orchestrator(
            retriever=retriever,
            graph_driver=graph_driver,
            planner=planner,
            database=database,
            max_agent_tasks=max_tasks,
        )

        if args.engine == "langgraph":
            # Import only when selected so the legacy engine remains usable without LangGraph.
            from exotrace.agents.langgraph_workflow import LangGraphInvestigationWorkflow

            # Planning previews remain uncheckpointed; only specialist execution is persisted.
            # This lets the CLI check credentials before beginning a resumable execution thread.
            workflow = LangGraphInvestigationWorkflow(orchestrator)
            if saved_plan is not None:
                # Use the reviewed plan or plan restored from the interrupted checkpoint.
                plan = saved_plan
                preview_report = None
            else:
                # A fresh invocation generates exactly one plan, then either previews or executes it.
                preview_report = workflow.investigate(args.query, execute=False)
                plan = preview_report.plan

            if args.plan_only:
                if preview_report is None:
                    raise ValueError("Internal error: a saved plan cannot be used in preview mode.")
                report = preview_report
            elif plan.disposition is not PlanDisposition.READY:
                if checkpointer is not None:
                    checkpoint_workflow = LangGraphInvestigationWorkflow(
                        orchestrator,
                        checkpointer=checkpointer,
                    )
                    report = checkpoint_workflow.execute_plan(
                        plan,
                        thread_id=checkpoint_thread_id,
                    )
                else:
                    report = workflow.execute_plan(plan)
            else:
                planned_tool_ids = {
                    tool_id
                    for planned_task in plan.tasks
                    for tool_id in orchestrator.agent_descriptor(
                        planned_task.agent_id
                    ).allowed_tool_ids
                }
                authentication_required = {
                    descriptor.tool_id
                    for descriptor in orchestrator.tool_descriptors()
                    if descriptor.requires_authentication
                }
                configured_password = settings.get("NEO4J_PASSWORD", "").strip()
                if planned_tool_ids & authentication_required and not configured_password:
                    password = getpass(
                        "Neo4j password required by the selected specialist tool: "
                    ).strip()
                    if not password:
                        raise ValueError(
                            "A Neo4j password is required by the selected graph investigation task."
                        )
                    graph_driver.close()
                    graph_driver = _create_graph_driver(settings, password_override=password)
                    orchestrator = _build_orchestrator(
                        retriever=retriever,
                        graph_driver=graph_driver,
                        planner=planner,
                        database=database,
                        max_agent_tasks=max_tasks,
                    )
                workflow = LangGraphInvestigationWorkflow(
                    orchestrator,
                    checkpointer=checkpointer,
                )
                report = workflow.execute_plan(plan, thread_id=checkpoint_thread_id)
        else:
            # Keep the current implementation as the default fallback while LangGraph is
            # validated against the same local scenarios and full test suite.
            plan = saved_plan if saved_plan is not None else orchestrator.create_plan(args.query)

            if args.plan_only:
                report_status = {
                    PlanDisposition.READY: InvestigationStatus.PLANNED,
                    PlanDisposition.NEEDS_CLARIFICATION: InvestigationStatus.NEEDS_CLARIFICATION,
                    PlanDisposition.UNSUPPORTED: InvestigationStatus.UNSUPPORTED,
                }[plan.disposition]
                now = datetime.now(UTC).isoformat()
                report = InvestigationReport(
                    question=plan.question,
                    status=report_status,
                    plan=plan,
                    started_at_utc=now,
                    completed_at_utc=now,
                )
            elif plan.disposition is not PlanDisposition.READY:
                report = orchestrator.execute_plan(plan)
            else:
                planned_tool_ids = {
                    tool_id
                    for planned_task in plan.tasks
                    for tool_id in orchestrator.agent_descriptor(planned_task.agent_id).allowed_tool_ids
                }
                authentication_required = {
                    descriptor.tool_id
                    for descriptor in orchestrator.tool_descriptors()
                    if descriptor.requires_authentication
                }
                configured_password = settings.get("NEO4J_PASSWORD", "").strip()
                if planned_tool_ids & authentication_required and not configured_password:
                    password = getpass(
                        "Neo4j password required by the selected specialist tool: "
                    ).strip()
                    if not password:
                        raise ValueError(
                            "A Neo4j password is required by the selected graph investigation task."
                        )
                    graph_driver.close()
                    graph_driver = _create_graph_driver(settings, password_override=password)
                    orchestrator = _build_orchestrator(
                        retriever=retriever,
                        graph_driver=graph_driver,
                        planner=planner,
                        database=database,
                        max_agent_tasks=max_tasks,
                    )
                report = orchestrator.execute_plan(plan)

        print(render_investigation_report(report, orchestrator))
        if args.save_json:
            output_path = args.save_json
            if not output_path.is_absolute():
                output_path = PROJECT_ROOT / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"\nInvestigation JSON: {output_path}")
        if report.status is InvestigationStatus.FAILED:
            return 1
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, PlannerError) as exc:
        print(f"ERROR running ExoTrace investigation: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR running ExoTrace investigation: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if checkpoint_context is not None:
            checkpoint_context.__exit__(*sys.exc_info())
        if graph_driver is not None:
            graph_driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
