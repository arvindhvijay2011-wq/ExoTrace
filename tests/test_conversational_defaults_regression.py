"""Regression tests for conversational defaults that preserve ExoTrace's older contracts."""

from __future__ import annotations

import json
from typing import Any, Mapping

from exotrace.agents.catalogue_data import CatalogueDataAgent
from exotrace.agents.contracts import AgentTask
from exotrace.agents.planning import OpenAIResponsesTaskPlanner
from exotrace.contracts import EvidenceReference
from exotrace.tools.contracts import ToolResult, ToolStatus


class RecordingExecutor:
    """Record one request and return a small source-backed fixture without external services."""

    def __init__(self) -> None:
        self.request: Any = None

    def execute(self, request: Any) -> ToolResult:
        self.request = request
        evidence = EvidenceReference(
            evidence_id="catalogue:planet-a",
            source_id="record:planet-a",
            title="Planet A catalogue record",
            excerpt='{"pl_name":"Planet A","hostname":"Star A","pl_orbper":"3.5"}',
            source_kind="catalogue_record",
            record_id="record:planet-a",
            snapshot_id="snapshot:test",
        )
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.SUCCEEDED,
            data={"matched_count": 1, "returned_count": 1, "truncated": False},
            evidence=(evidence,),
        )


def make_task(context: Mapping[str, Any]) -> AgentTask:
    """Build a permitted catalogue task for a fake tool executor."""
    return AgentTask(
        task_id="catalogue-test",
        question="Tell me about Planet A.",
        objective="Retrieve catalogue properties.",
        required_capabilities=("catalogue.raw_values",),
        allowed_tool_ids=("catalogue.lookup",),
        context=context,
    )


def test_broad_request_defaults_to_live_fields_and_keeps_compact_filter_contract() -> None:
    fields = ("pl_name", "hostname", "pl_orbper")
    agent = CatalogueDataAgent(available_fields=fields)
    task = make_task({"filters": [{"field": "pl_name", "value": "Planet A"}]})
    executor = RecordingExecutor()

    result = agent.run(task, tools=executor)

    assert result.status.value == "succeeded"
    assert executor.request.arguments["fields"] == list(fields)
    assert executor.request.arguments["filters"] == {"pl_name": "Planet A"}
    assert agent.descriptor.task_context_schema["properties"]["filters"]["type"] == "array"
    assert agent.descriptor.task_context_schema["required"] == ["filters"]


def test_legacy_mapping_filters_remain_supported() -> None:
    agent = CatalogueDataAgent(available_fields=("pl_name", "hostname", "pl_orbper"))
    executor = RecordingExecutor()

    result = agent.run(
        make_task({"filters": {"pl_name": "Planet A"}, "fields": ["pl_name"]}),
        tools=executor,
    )

    assert result.status.value == "succeeded"
    assert executor.request.arguments["filters"] == {"pl_name": "Planet A"}
    assert executor.request.arguments["fields"] == ["pl_name"]


def test_placeholder_filter_still_fails_closed_before_tool_execution() -> None:
    agent = CatalogueDataAgent(available_fields=("pl_name", "hostname"))
    executor = RecordingExecutor()

    result = agent.run(
        make_task({"filters": [{"field": "pl_name", "value": "null"}]}),
        tools=executor,
    )

    assert result.status.value == "failed"
    assert result.error_code == "invalid_structured_filters"
    assert executor.request is None


def test_duplicate_filter_fields_still_fail_closed_before_tool_execution() -> None:
    agent = CatalogueDataAgent(available_fields=("pl_name", "hostname"))
    executor = RecordingExecutor()

    result = agent.run(
        make_task(
            {
                "filters": [
                    {"field": "pl_name", "value": "Planet A"},
                    {"field": "pl_name", "value": "Planet B"},
                ]
            }
        ),
        tools=executor,
    )

    assert result.status.value == "failed"
    assert result.error_code == "invalid_structured_filters"
    assert executor.request is None


def test_planner_keeps_legacy_completeness_rules_and_omits_broad_fields() -> None:
    fields = ("pl_name", "hostname", "pl_orbper")
    agent = CatalogueDataAgent(available_fields=fields)
    captured: dict[str, Any] = {}
    output = {
        "disposition": "ready",
        "summary": "Retrieve the catalogue profile.",
        "tasks": [
            {
                "task_key": "catalogue-profile",
                "agent_id": "catalogue_data",
                "question": "Tell me about Planet A.",
                "objective": "Retrieve available properties for Planet A.",
                "required_capabilities": ["catalogue.raw_values"],
                "depends_on": [],
                "context": {
                    "filters": [{"field": "pl_name", "value": "Planet A"}],
                    "fields": None,
                    "match_mode": None,
                    "limit": None,
                },
            }
        ],
        "clarifying_questions": [],
    }

    def fake_post_json(
        _url: str,
        _headers: Mapping[str, str],
        body: Mapping[str, Any],
        _timeout: float,
    ) -> dict[str, Any]:
        captured["body"] = dict(body)
        return {"output_text": json.dumps(output)}

    planner = OpenAIResponsesTaskPlanner(
        api_key="offline-test-key",
        model="offline-test-model",
        post_json=fake_post_json,
    )
    plan = planner.create_plan(
        "Tell me about Planet A.",
        agents=(agent.descriptor,),
        tools=(),
        max_tasks=3,
    )

    assert plan.tasks[0].context == {
        "filters": [{"field": "pl_name", "value": "Planet A"}]
    }
    system_prompt = captured["body"]["input"][0]["content"][0]["text"]
    assert "PLAN COMPLETENESS IS REQUIRED" in system_prompt
    assert "Never emit literal placeholder values" in system_prompt
    assert "omit fields" in system_prompt
    assert "Do not ask the user to enumerate" in system_prompt
