"""Regression tests for defaulting optional aspect clarifications to a broad profile."""

from __future__ import annotations

from exotrace.agents.catalogue_data import CatalogueDataAgent
from exotrace.agents.orchestrator import validate_context_against_schema
from exotrace.agents.planning import InvestigationPlan, PlanDisposition
from exotrace.agents.planet_identifier_resolution import CataloguePlanetIdentifierResolver

PLANET_NAME = "2MASS J03590986+2009361 b"
HOST_NAME = "2MASS J03590986+2009361"
SCOPE_QUESTION = (
    "What specific information are you looking for about the planet "
    f"{PLANET_NAME}? For instance, do you want details on its physical parameters, "
    "discovery method, or something else?"
)


def make_clarification_plan(
    question: str,
    clarifying_questions: tuple[str, ...] = (SCOPE_QUESTION,),
) -> InvestigationPlan:
    """Return a valid non-executable plan that asks for clarification."""
    return InvestigationPlan(
        question=question,
        disposition=PlanDisposition.NEEDS_CLARIFICATION,
        summary="The planner requests clarification.",
        tasks=(),
        clarifying_questions=clarifying_questions,
        planner_model="offline-regression-model",
    )


def make_resolver() -> CataloguePlanetIdentifierResolver:
    """Build the resolver from source-like identities and the live catalogue contract."""
    catalogue_agent = CatalogueDataAgent(
        available_fields=("pl_name", "hostname", "pl_rade", "pl_bmasse")
    )
    return CataloguePlanetIdentifierResolver(
        ((PLANET_NAME, HOST_NAME),),
        agent_descriptors=(catalogue_agent.descriptor,),
    )


def test_unique_explicit_planet_and_scope_preference_uses_default_catalogue_profile() -> None:
    question = f"Tell me something about this planet {PLANET_NAME}."
    clarification = make_clarification_plan(question)

    resolved = make_resolver().resolve_plan(clarification)

    assert resolved.disposition is PlanDisposition.READY
    assert resolved.question == question
    assert resolved.clarifying_questions == ()
    assert len(resolved.tasks) == 1
    task = resolved.tasks[0]
    assert task.agent_id == "catalogue_data"
    assert task.context == {"filters": [{"field": "pl_name", "value": PLANET_NAME}]}
    # Omitted fields preserve CatalogueDataAgent's established live-field default.
    assert "fields" not in task.context
    assert task.required_capabilities == (
        "catalogue.lookup",
        "catalogue.raw_values",
        "source.provenance",
    )
    catalogue_descriptor = CatalogueDataAgent(
        available_fields=("pl_name", "hostname", "pl_rade", "pl_bmasse")
    ).descriptor
    validate_context_against_schema(task.context, catalogue_descriptor.task_context_schema)


def test_entity_identity_clarification_is_not_overridden() -> None:
    question = f"Tell me about {PLANET_NAME}."
    plan = make_clarification_plan(question, ("Which planet do you mean?",))

    resolved = make_resolver().resolve_plan(plan)

    assert resolved is plan
    assert resolved.disposition is PlanDisposition.NEEDS_CLARIFICATION


def test_broad_profile_fallback_does_not_choose_between_multiple_named_planets() -> None:
    second_planet = "Kepler-10 b"
    catalogue_agent = CatalogueDataAgent(available_fields=("pl_name", "hostname"))
    resolver = CataloguePlanetIdentifierResolver(
        ((PLANET_NAME, HOST_NAME), (second_planet, "Kepler-10")),
        agent_descriptors=(catalogue_agent.descriptor,),
    )
    question = f"Tell me something about {PLANET_NAME} and {second_planet}."
    plan = make_clarification_plan(question)

    resolved = resolver.resolve_plan(plan)

    assert resolved is plan
    assert resolved.disposition is PlanDisposition.NEEDS_CLARIFICATION


def test_broad_profile_fallback_requires_live_catalogue_descriptor() -> None:
    resolver = CataloguePlanetIdentifierResolver(((PLANET_NAME, HOST_NAME),))
    plan = make_clarification_plan(f"Tell me something about {PLANET_NAME}.")

    resolved = resolver.resolve_plan(plan)

    assert resolved is plan
    assert resolved.disposition is PlanDisposition.NEEDS_CLARIFICATION
