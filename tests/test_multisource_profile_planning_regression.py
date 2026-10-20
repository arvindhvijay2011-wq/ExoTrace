"""Regression tests for source-complete broad planet profiles."""

from __future__ import annotations

from exotrace.agents.catalogue_data import CatalogueDataAgent
from exotrace.agents.graph_investigation import GraphInvestigationAgent
from exotrace.agents.literature_definition import LiteratureDefinitionAgent
from exotrace.agents.orchestrator import validate_context_against_schema
from exotrace.agents.planning import InvestigationPlan, PlanDisposition, PlannedAgentTask
from exotrace.agents.planet_identifier_resolution import CataloguePlanetIdentifierResolver

PLANET_NAME = "2MASS J03590986+2009361 b"
HOST_NAME = "2MASS J03590986+2009361"
QUESTION = f"Tell me something about this planet {PLANET_NAME}."
SCOPE_QUESTION = (
    f"What specific information are you looking for about the planet {PLANET_NAME}? "
    "For instance, do you want details on its physical parameters, discovery method, "
    "or something else?"
)


def registered_descriptors():
    """Return the current catalogue, graph, and reference specialist contracts."""
    return (
        CatalogueDataAgent(
            available_fields=("pl_name", "hostname", "pl_rade", "pl_bmasse", "disc_year")
        ).descriptor,
        GraphInvestigationAgent().descriptor,
        LiteratureDefinitionAgent().descriptor,
    )


def resolver(*, max_agent_tasks: int = 5) -> CataloguePlanetIdentifierResolver:
    """Build the application-configured resolver from source-like planet identities."""
    return CataloguePlanetIdentifierResolver(
        ((PLANET_NAME, HOST_NAME),),
        agent_descriptors=registered_descriptors(),
        include_context_sources=True,
        max_agent_tasks=max_agent_tasks,
    )


def clarification_plan(question: str = QUESTION) -> InvestigationPlan:
    """Build a preference-only clarification plan with no executable tasks."""
    return InvestigationPlan(
        question=question,
        disposition=PlanDisposition.NEEDS_CLARIFICATION,
        summary="The planner requests the user's preferred information categories.",
        tasks=(),
        clarifying_questions=(SCOPE_QUESTION,),
        planner_model="offline-multisource-test-model",
    )


def ready_catalogue_profile(*, fields: list[str] | None = None) -> InvestigationPlan:
    """Build a READY plan containing a canonical broad or field-limited catalogue task."""
    context = {"filters": [{"field": "pl_name", "value": PLANET_NAME}]}
    if fields is not None:
        context["fields"] = fields
    return InvestigationPlan(
        question=QUESTION,
        disposition=PlanDisposition.READY,
        summary="Retrieve the catalogue profile.",
        tasks=(
            PlannedAgentTask(
                agent_id="catalogue_data",
                question=QUESTION,
                objective="Retrieve the requested catalogue information.",
                required_capabilities=("catalogue.lookup", "catalogue.raw_values"),
                context=context,
                task_key="catalogue-profile",
            ),
        ),
        clarifying_questions=(),
        planner_model="offline-multisource-test-model",
    )


def test_preference_clarification_defaults_to_catalogue_graph_and_reference_sources() -> None:
    original = clarification_plan()

    resolved = resolver().resolve_plan(original)

    assert resolved.disposition is PlanDisposition.READY
    assert resolved.clarifying_questions == ()
    assert [task.agent_id for task in resolved.tasks] == [
        "catalogue_data",
        "graph_investigation",
        "literature_definition",
    ]
    assert resolved.tasks[0].context == {
        "filters": [{"field": "pl_name", "value": PLANET_NAME}]
    }
    assert resolved.tasks[1].context == {
        "operation": "planet_context",
        "planet_name": PLANET_NAME,
    }
    assert resolved.tasks[2].context == {}
    assert len({task.task_key for task in resolved.tasks}) == len(resolved.tasks)
    assert all(not task.depends_on for task in resolved.tasks)
    descriptors = {item.agent_id: item for item in registered_descriptors()}
    for task in resolved.tasks:
        validate_context_against_schema(
            task.context, descriptors[task.agent_id].task_context_schema
        )
    # The original proposal is immutable and remains a clarification plan.
    assert original.disposition is PlanDisposition.NEEDS_CLARIFICATION
    assert original.tasks == ()


def test_ready_broad_catalogue_profile_is_supplemented_with_missing_sources() -> None:
    original = ready_catalogue_profile()

    resolved = resolver().resolve_plan(original)

    assert [task.agent_id for task in resolved.tasks] == [
        "catalogue_data",
        "graph_investigation",
        "literature_definition",
    ]
    assert resolved.tasks[1].context["planet_name"] == PLANET_NAME
    assert "supplemented with complementary source retrieval" in resolved.summary


def test_field_limited_catalogue_plan_is_not_expanded_to_every_source() -> None:
    original = ready_catalogue_profile(fields=["pl_name", "pl_rade"])

    resolved = resolver().resolve_plan(original)

    assert resolved is original
    assert len(resolved.tasks) == 1
    assert resolved.tasks[0].context["fields"] == ["pl_name", "pl_rade"]


def test_broad_profile_does_not_exceed_configured_task_budget() -> None:
    original = clarification_plan()

    resolved = resolver(max_agent_tasks=2).resolve_plan(original)

    assert resolved is original
    assert resolved.disposition is PlanDisposition.NEEDS_CLARIFICATION
    assert resolved.tasks == ()


def test_source_completion_requires_one_explicit_canonical_planet() -> None:
    second_planet = "Kepler-10 b"
    two_planet_resolver = CataloguePlanetIdentifierResolver(
        ((PLANET_NAME, HOST_NAME), (second_planet, "Kepler-10")),
        agent_descriptors=registered_descriptors(),
        include_context_sources=True,
    )
    question = f"Tell me something about {PLANET_NAME} and {second_planet}."
    original = clarification_plan(question)

    resolved = two_planet_resolver.resolve_plan(original)

    assert resolved is original
    assert resolved.disposition is PlanDisposition.NEEDS_CLARIFICATION
