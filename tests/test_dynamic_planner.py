"""Offline tests for dynamic OpenAI task planning."""

from __future__ import annotations

import json
from typing import Any, Mapping

import pytest

from exotrace.agents.contracts import AgentDescriptor
from exotrace.agents.planning import (
    InvestigationPlan,
    OpenAIResponsesTaskPlanner,
    PlanDisposition,
    PlannedAgentTask,
    PlannerError,
)
from exotrace.tools.contracts import ToolDescriptor


def make_agent(agent_id: str = "literature") -> AgentDescriptor:
    """Create a planner-facing agent descriptor with a declared task schema."""
    return AgentDescriptor(
        agent_id=agent_id,
        name="Literature specialist",
        responsibility="Retrieve reference passages and definitions.",
        capabilities=("literature.retrieve", "parameter.definition"),
        allowed_tool_ids=("literature.search",),
        task_context_schema={
            "type": "object",
            "properties": {
                "search_query": {"type": "string", "minLength": 1},
                "top_k": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        },
    )


def make_tool() -> ToolDescriptor:
    """Create a minimal tool descriptor for the planner input."""
    return ToolDescriptor(
        tool_id="literature.search",
        name="Reference search",
        purpose="Search the frozen reference corpus.",
        capabilities=("literature.retrieve",),
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    )


def planner_payload(
    *,
    disposition: str = "ready",
    tasks: list[dict[str, Any]] | None = None,
    summary: str = "Use literature retrieval for the question.",
    clarifying_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Return a Responses API payload carrying a structured planner result."""
    content = {
        "disposition": disposition,
        "summary": summary,
        "tasks": tasks if tasks is not None else [
            {
                "task_key": "literature-definition",
                "agent_id": "literature",
                "question": "Find the authoritative reference passage.",
                "objective": "Retrieve relevant source excerpts.",
                "required_capabilities": ["literature.retrieve"],
                "depends_on": [],
                "context": {"search_query": "orbital eccentricity", "top_k": None},
            }
        ],
        "clarifying_questions": clarifying_questions or [],
    }
    return {"output_text": json.dumps(content)}


def make_planner(response: dict[str, Any]) -> tuple[OpenAIResponsesTaskPlanner, dict[str, Any]]:
    """Create planner with a capturing fake HTTP transport."""
    captured: dict[str, Any] = {}

    def fake_post_json(
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        captured.update({"url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        return response

    planner = OpenAIResponsesTaskPlanner(
        api_key="test-key",
        model="configured-test-model",
        post_json=fake_post_json,
    )
    return planner, captured


def test_planner_builds_dynamic_agent_enum_and_context_schemas() -> None:
    planner, captured = make_planner(planner_payload())

    plan = planner.create_plan(
        "What does orbital eccentricity describe?",
        agents=(make_agent(),),
        tools=(make_tool(),),
        max_tasks=3,
    )

    assert plan.disposition is PlanDisposition.READY
    assert plan.tasks[0].context == {"search_query": "orbital eccentricity"}
    assert plan.tasks[0].task_key == "literature-definition"
    assert plan.tasks[0].depends_on == ()
    schema = captured["body"]["text"]["format"]["schema"]
    task_branches = schema["properties"]["tasks"]["items"]["anyOf"]
    assert len(task_branches) == 1
    task_schema = task_branches[0]
    assert task_schema["properties"]["agent_id"]["enum"] == ["literature"]
    assert "task_key" in task_schema["required"]
    assert "depends_on" in task_schema["required"]
    assert task_schema["properties"]["depends_on"]["type"] == "array"
    context_schema = task_schema["properties"]["context"]
    assert context_schema["type"] == "object"
    assert context_schema["additionalProperties"] is False
    assert set(context_schema["required"]) == {"search_query", "top_k"}
    assert context_schema["properties"]["top_k"]["anyOf"][-1] == {"type": "null"}
    user_text = captured["body"]["input"][1]["content"][0]["text"]
    user_payload = json.loads(user_text)
    assert user_payload["registered_agents"][0]["task_context_schema"]["properties"][
        "search_query"
    ]["type"] == "string"
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_planner_returns_clarification_without_tasks() -> None:
    planner, _captured = make_planner(
        planner_payload(
            disposition="needs_clarification",
            tasks=[],
            summary="A required entity is ambiguous.",
            clarifying_questions=["Which planet do you mean?"],
        )
    )

    plan = planner.create_plan(
        "Compare it with another planet.",
        agents=(make_agent(),),
        tools=(make_tool(),),
        max_tasks=3,
    )

    assert plan.disposition is PlanDisposition.NEEDS_CLARIFICATION
    assert plan.tasks == ()
    assert plan.clarifying_questions == ("Which planet do you mean?",)


def test_planner_rejects_context_that_is_not_an_object() -> None:
    response = planner_payload()
    parsed = json.loads(response["output_text"])
    parsed["tasks"][0]["context"] = ["not", "an", "object"]
    planner, _captured = make_planner({"output_text": json.dumps(parsed)})

    with pytest.raises(PlannerError, match="context must be a JSON object"):
        planner.create_plan(
            "Question",
            agents=(make_agent(),),
            tools=(make_tool(),),
            max_tasks=3,
        )


def test_planner_rejects_unregistered_agent_in_task() -> None:
    response = planner_payload()
    parsed = json.loads(response["output_text"])
    parsed["tasks"][0]["agent_id"] = "unregistered-agent"
    planner, _captured = make_planner({"output_text": json.dumps(parsed)})

    with pytest.raises(PlannerError, match="unknown registered agent"):
        planner.create_plan(
            "Question",
            agents=(make_agent(),),
            tools=(make_tool(),),
            max_tasks=3,
        )


def test_planner_enforces_configured_task_limit() -> None:
    response = planner_payload()
    parsed = json.loads(response["output_text"])
    parsed["tasks"] = parsed["tasks"] * 2
    planner, _captured = make_planner({"output_text": json.dumps(parsed)})

    with pytest.raises(PlannerError, match="exceeding the configured limit"):
        planner.create_plan(
            "Question",
            agents=(make_agent(),),
            tools=(make_tool(),),
            max_tasks=1,
        )


def test_planner_rejects_empty_agent_registry_without_api_call() -> None:
    planner, captured = make_planner(planner_payload())

    with pytest.raises(PlannerError, match="No specialist agents"):
        planner.create_plan("Question", agents=(), tools=(make_tool(),), max_tasks=3)

    assert captured == {}


def test_planner_rejects_blank_question_without_api_call() -> None:
    planner, captured = make_planner(planner_payload())

    with pytest.raises(ValueError, match="cannot be empty"):
        planner.create_plan("   ", agents=(make_agent(),), tools=(make_tool(),), max_tasks=3)

    assert captured == {}


def test_plan_contract_rejects_executable_tasks_in_non_ready_state() -> None:
    with pytest.raises(ValueError, match="must not contain executable tasks"):
        InvestigationPlan(
            question="Question",
            disposition=PlanDisposition.UNSUPPORTED,
            summary="No specialist can do this.",
            tasks=(
                PlannedAgentTask(
                    agent_id="literature",
                    question="Question",
                    objective="Objective",
                    required_capabilities=("literature.retrieve",),
                ),
            ),
            planner_model="configured-test-model",
        )


def test_catalogue_agent_schema_uses_live_source_columns() -> None:
    from exotrace.agents.catalogue_data import CatalogueDataAgent

    agent = CatalogueDataAgent(available_fields=("pl_name", "hostname", "pl_orbper"))
    field_schema = agent.descriptor.task_context_schema["properties"]["fields"]["items"]

    assert field_schema["enum"] == ["pl_name", "hostname", "pl_orbper"]
    filters_schema = agent.descriptor.task_context_schema["properties"]["filters"]
    assert filters_schema["type"] == "array"
    assert filters_schema["items"]["properties"]["field"]["enum"] == [
        "pl_name", "hostname", "pl_orbper"
    ]
    assert filters_schema["items"]["additionalProperties"] is False


def test_catalogue_context_schema_can_be_compiled_for_strict_object_output() -> None:
    from exotrace.agents.catalogue_data import CatalogueDataAgent
    from exotrace.agents.planning import OpenAIResponsesTaskPlanner, _remove_optional_nulls

    agent = CatalogueDataAgent(available_fields=("pl_name", "hostname", "pl_orbper"))
    descriptor = agent.descriptor
    schema = OpenAIResponsesTaskPlanner._response_schema((descriptor,))
    branch = schema["properties"]["tasks"]["items"]["anyOf"][0]
    context_schema = branch["properties"]["context"]
    filters_schema = context_schema["properties"]["filters"]

    assert filters_schema["type"] == "array"
    assert filters_schema["items"]["additionalProperties"] is False
    assert set(filters_schema["items"]["required"]) == {"field", "value"}
    assert filters_schema["items"]["properties"]["field"]["enum"] == [
        "pl_name", "hostname", "pl_orbper"
    ]

    restored_context = _remove_optional_nulls(
        {
            "filters": [{"field": "pl_name", "value": "Planet A"}],
            "fields": ["pl_name"],
            "match_mode": None,
            "limit": None,
        },
        descriptor.task_context_schema,
    )
    assert restored_context == {
        "filters": [{"field": "pl_name", "value": "Planet A"}],
        "fields": ["pl_name"],
    }


def test_graph_agent_schema_uses_tool_declared_operations() -> None:
    from exotrace.agents.graph_investigation import GraphInvestigationAgent
    from exotrace.tools.graph_investigation import GraphInvestigationTool

    agent = GraphInvestigationAgent()
    operation_schema = agent.descriptor.task_context_schema["properties"]["operation"]

    assert operation_schema["enum"] == list(GraphInvestigationTool.SUPPORTED_OPERATIONS)


def test_graph_tool_declares_authentication_requirement_in_its_contract() -> None:
    from exotrace.tools.graph_investigation import GraphInvestigationTool

    # Descriptor inspection does not open a Neo4j connection.
    class UnusedDriver:
        def session(self, *, database: str) -> Any:
            raise AssertionError("Descriptor access should not open a Neo4j session.")

    descriptor = GraphInvestigationTool(UnusedDriver()).descriptor

    assert descriptor.requires_authentication is True
    assert descriptor.read_only is True


def test_planner_preserves_explicit_prior_task_dependencies() -> None:
    payload = planner_payload(
        tasks=[
            {
                "task_key": "planet-a",
                "agent_id": "literature",
                "question": "Find source material for planet A.",
                "objective": "Retrieve source material.",
                "required_capabilities": ["literature.retrieve"],
                "depends_on": [],
                "context": {"search_query": "planet A", "top_k": None},
            },
            {
                "task_key": "planet-b-context",
                "agent_id": "literature",
                "question": "Retrieve follow-up background after planet A lookup.",
                "objective": "Retrieve additional context.",
                "required_capabilities": ["literature.retrieve"],
                "depends_on": ["planet-a"],
                "context": {"search_query": "planet A background", "top_k": None},
            },
        ]
    )
    planner, _captured = make_planner(payload)

    plan = planner.create_plan(
        "Research planet A and its background.",
        agents=(make_agent(),),
        tools=(make_tool(),),
        max_tasks=3,
    )

    assert plan.tasks[0].task_key == "planet-a"
    assert plan.tasks[1].depends_on == ("planet-a",)


def test_plan_rejects_unknown_or_forward_dependencies() -> None:
    with pytest.raises(ValueError, match="must appear earlier"):
        InvestigationPlan(
            question="Question",
            disposition=PlanDisposition.READY,
            summary="Test dependencies.",
            tasks=(
                PlannedAgentTask(
                    agent_id="literature",
                    question="Question",
                    objective="Retrieve source.",
                    required_capabilities=("literature.retrieve",),
                    task_key="task-a",
                    depends_on=("task-b",),
                ),
                PlannedAgentTask(
                    agent_id="literature",
                    question="Question B",
                    objective="Retrieve source B.",
                    required_capabilities=("literature.retrieve",),
                    task_key="task-b",
                ),
            ),
            planner_model="offline-test-model",
        )


def test_planner_prompt_requires_complete_task_graph_coverage() -> None:
    """Keep the planner's completeness and dependency instructions explicit."""
    planner, captured = make_planner(planner_payload())

    planner.create_plan(
        "Compare values from two records and calculate a ratio.",
        agents=(make_agent(),),
        tools=(make_tool(),),
        max_tasks=3,
    )

    system_prompt = captured["body"]["input"][0]["content"][0]["text"]
    assert "PLAN COMPLETENESS IS REQUIRED" in system_prompt
    assert "the tasks array is authoritative" in system_prompt
    assert "a separate calculation task that depends on all of them" in system_prompt
    assert "compare the summary to the actual task array" in system_prompt
