"""Resolve planner identifiers and safe broad-profile defaults from catalogue evidence.

Canonical ``pl_name`` and hostname identities come from the checksum-verified catalogue. A
shortened task identifier is repaired only when the complete planet name is explicit in the
question and uniquely resolves to the supplied hostname. When a planner asks only for a preferred
level of detail despite one uniquely named planet, the resolver can create a minimal catalogue
profile task from a live agent contract. Ambiguous identities and host-star operations are left
unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Mapping

from exotrace.agents.contracts import AgentDescriptor
from exotrace.agents.planning import (
    InvestigationPlan,
    PlanDisposition,
    PlannedAgentTask,
)


class CataloguePlanetIdentifierResolver:
    """Safely align planner contexts with complete planet names explicitly in the question."""

    def __init__(
        self,
        planet_host_identities: Sequence[tuple[str, str]],
        *,
        agent_descriptors: Sequence[AgentDescriptor] = (),
    ) -> None:
        """Create a resolver from source identities and optional live agent contracts."""
        if any(not isinstance(item, AgentDescriptor) for item in agent_descriptors):
            raise TypeError("agent_descriptors must contain AgentDescriptor objects.")
        self._agent_descriptors = tuple(agent_descriptors)
        identities: list[tuple[str, str]] = []
        seen_names: dict[str, str] = {}
        for index, identity in enumerate(planet_host_identities, start=1):
            if not isinstance(identity, (tuple, list)) or len(identity) != 2:
                raise ValueError(
                    f"Planet identity {index} must contain a planet name and hostname."
                )
            planet_name, hostname = identity
            if not isinstance(planet_name, str) or not planet_name.strip():
                raise ValueError(f"Planet identity {index} has an invalid planet name.")
            if not isinstance(hostname, str) or not hostname.strip():
                raise ValueError(f"Planet identity {index} has an invalid hostname.")
            canonical_name = planet_name.strip()
            canonical_host = hostname.strip()
            name_key = canonical_name.casefold()
            previous_host = seen_names.get(name_key)
            if previous_host is not None:
                if previous_host.casefold() != canonical_host.casefold():
                    raise ValueError(
                        f"Planet name {canonical_name!r} maps to conflicting hostnames."
                    )
                raise ValueError(f"Planet name {canonical_name!r} is duplicated.")
            seen_names[name_key] = canonical_host
            identities.append((canonical_name, canonical_host))
        if not identities:
            raise ValueError("At least one validated planet identity is required.")
        self._identities = tuple(identities)

    def resolve_plan(self, plan: InvestigationPlan) -> InvestigationPlan:
        """Correct supported task-context identifiers only when one explicit source match exists.

        The original plan is immutable. If nothing can be resolved unambiguously, the same plan
        object is returned unchanged. The orchestrator validates both the incoming and returned
        plans against live agent/tool contracts.
        """
        if not isinstance(plan, InvestigationPlan):
            raise TypeError("plan must be an InvestigationPlan.")
        mentioned = self._explicitly_mentioned_planets(plan.question)
        if plan.disposition is PlanDisposition.NEEDS_CLARIFICATION:
            return self._default_broad_profile_when_scope_is_optional(plan, mentioned)
        if plan.disposition is not PlanDisposition.READY or not mentioned:
            return plan

        resolved_tasks: list[PlannedAgentTask] = []
        changed = False
        for task in plan.tasks:
            context = dict(task.context)
            task_changed = self._resolve_catalogue_filter(context, mentioned)
            task_changed = self._resolve_graph_identifier(context, mentioned) or task_changed
            if task_changed:
                resolved_tasks.append(replace(task, context=context))
                changed = True
            else:
                resolved_tasks.append(task)

        if not changed:
            return plan
        return replace(plan, tasks=tuple(resolved_tasks))

    def _default_broad_profile_when_scope_is_optional(
        self,
        plan: InvestigationPlan,
        mentioned: tuple[tuple[str, str], ...],
    ) -> InvestigationPlan:
        """Use a source-backed catalogue profile instead of asking a preference-only question.

        This fallback is deliberately narrow: it requires exactly one complete canonical planet
        name in the question, every planner clarification to be about choosing the desired level
        or aspect of detail, and exactly one registered catalogue agent whose schema supports a
        structured ``pl_name`` filter. Entity ambiguity and other required decisions remain
        clarification outcomes.
        """
        if len(mentioned) != 1 or not self._is_scope_preference_clarification(
            plan.clarifying_questions
        ):
            return plan
        descriptor = self._catalogue_profile_descriptor()
        if descriptor is None:
            return plan

        planet_name, _hostname = mentioned[0]
        task = PlannedAgentTask(
            agent_id=descriptor.agent_id,
            question=plan.question,
            objective=(
                "Retrieve the validated catalogue profile for the explicitly identified planet, "
                "using the catalogue agent's source-defined default field set."
            ),
            required_capabilities=descriptor.capabilities,
            context={"filters": [{"field": "pl_name", "value": planet_name}]},
            task_key="default-catalogue-profile",
            depends_on=(),
        )
        return InvestigationPlan(
            question=plan.question,
            disposition=PlanDisposition.READY,
            summary=(
                "The question identifies one canonical planet in the validated catalogue. "
                "Using the broad catalogue profile as the default avoids asking the user to "
                "choose among optional information categories."
            ),
            tasks=(task,),
            clarifying_questions=(),
            planner_model=plan.planner_model,
        )

    @staticmethod
    def _is_scope_preference_clarification(questions: Sequence[str]) -> bool:
        """Recognize optional 'which aspects?' clarifications, not missing required inputs."""
        if not questions or any(
            not isinstance(item, str) or not item.strip() for item in questions
        ):
            return False
        preference_markers = (
            "what specific information",
            "what information are you looking for",
            "what kind of information",
            "what details are you looking for",
            "which details are you looking for",
            "what aspects are you interested in",
            "which aspects are you interested in",
            "what would you like to know",
            "which aspects would you like",
        )
        return all(
            any(marker in question.casefold() for marker in preference_markers)
            for question in questions
        )

    def _catalogue_profile_descriptor(self) -> AgentDescriptor | None:
        """Find the unique registered agent whose live schema supports canonical planet filters."""
        candidates: list[AgentDescriptor] = []
        for descriptor in self._agent_descriptors:
            if not {"catalogue.lookup", "catalogue.raw_values"}.issubset(
                set(descriptor.capabilities)
            ):
                continue
            schema = descriptor.task_context_schema
            properties = schema.get("properties", {})
            filter_schema = properties.get("filters") if isinstance(properties, Mapping) else None
            if not isinstance(filter_schema, Mapping) or filter_schema.get("type") != "array":
                continue
            item_schema = filter_schema.get("items")
            item_properties = (
                item_schema.get("properties", {}) if isinstance(item_schema, Mapping) else {}
            )
            field_schema = (
                item_properties.get("field") if isinstance(item_properties, Mapping) else None
            )
            value_schema = (
                item_properties.get("value") if isinstance(item_properties, Mapping) else None
            )
            if not isinstance(field_schema, Mapping) or not isinstance(value_schema, Mapping):
                continue
            enum_values = field_schema.get("enum")
            if isinstance(enum_values, list) and "pl_name" not in enum_values:
                continue
            required_item_keys = (
                set(item_schema.get("required", []))
                if isinstance(item_schema, Mapping)
                else set()
            )
            if required_item_keys and not {"field", "value"}.issubset(required_item_keys):
                continue
            required_context_keys = set(schema.get("required", []))
            if "filters" not in required_context_keys:
                continue
            candidates.append(descriptor)
        return candidates[0] if len(candidates) == 1 else None

    def _explicitly_mentioned_planets(self, question: str) -> tuple[tuple[str, str], ...]:
        """Find full source planet names explicitly present in the question, longest first."""
        if not isinstance(question, str) or not question:
            return ()
        found: list[tuple[str, str, int, int]] = []
        # Longest-first prevents a shorter source identifier from being treated as a second
        # entity when it occurs entirely inside a longer canonical identifier.
        ordered_identities = sorted(
            self._identities,
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for planet_name, hostname in ordered_identities:
            for start, end in self._bounded_occurrences(question, planet_name):
                if any(start >= old_start and end <= old_end for _, _, old_start, old_end in found):
                    continue
                found.append((planet_name, hostname, start, end))
        unique: dict[str, tuple[str, str]] = {}
        for planet_name, hostname, _start, _end in found:
            unique.setdefault(planet_name.casefold(), (planet_name, hostname))
        return tuple(unique.values())

    @staticmethod
    def _bounded_occurrences(text: str, identifier: str) -> tuple[tuple[int, int], ...]:
        """Return case-insensitive occurrences not embedded inside a larger word/token."""
        folded_text = text.casefold()
        folded_identifier = identifier.casefold()
        occurrences: list[tuple[int, int]] = []
        cursor = 0
        while True:
            start = folded_text.find(folded_identifier, cursor)
            if start < 0:
                break
            end = start + len(folded_identifier)
            before = folded_text[start - 1] if start else ""
            after = folded_text[end] if end < len(folded_text) else ""
            before_is_word = before.isalnum() or before == "_"
            after_is_word = after.isalnum() or after == "_"
            if not before_is_word and not after_is_word:
                occurrences.append((start, end))
            cursor = start + 1
        return tuple(occurrences)

    def _resolve_explicit_planet_for_identifier(
        self,
        raw_identifier: Any,
        mentioned: tuple[tuple[str, str], ...],
    ) -> str | None:
        """Return a canonical name only when the supplied value is that planet's host name."""
        if not isinstance(raw_identifier, str) or not raw_identifier.strip():
            return None
        target = raw_identifier.strip().casefold()
        matching_planets = {
            planet_name.casefold(): planet_name
            for planet_name, _hostname in mentioned
            if planet_name.casefold() == target
        }
        if len(matching_planets) == 1:
            return next(iter(matching_planets.values()))

        host_matches = {
            planet_name.casefold(): planet_name
            for planet_name, hostname in mentioned
            if hostname.casefold() == target
        }
        if len(host_matches) == 1:
            return next(iter(host_matches.values()))
        return None

    def _resolve_catalogue_filter(
        self,
        context: dict[str, Any],
        mentioned: tuple[tuple[str, str], ...],
    ) -> bool:
        """Repair only a structured ``pl_name`` filter for one explicit planet mention."""
        filters = context.get("filters")
        if not isinstance(filters, list):
            return False
        changed = False
        normalized_filters: list[Any] = []
        for clause in filters:
            if not isinstance(clause, Mapping) or clause.get("field") != "pl_name":
                normalized_filters.append(clause)
                continue
            correction = self._resolve_explicit_planet_for_identifier(
                clause.get("value"), mentioned
            )
            if correction is None or correction == clause.get("value"):
                normalized_filters.append(clause)
                continue
            corrected_clause = dict(clause)
            corrected_clause["value"] = correction
            normalized_filters.append(corrected_clause)
            changed = True
        if changed:
            context["filters"] = normalized_filters
        return changed

    def _resolve_graph_identifier(
        self,
        context: dict[str, Any],
        mentioned: tuple[tuple[str, str], ...],
    ) -> bool:
        """Repair planet operations, but never reinterpret a host-planets operation."""
        operation = context.get("operation")
        if operation not in {"planet_context", "planet_records"}:
            return False
        current_value = context.get("planet_name")
        correction = self._resolve_explicit_planet_for_identifier(current_value, mentioned)
        if correction is None or correction == current_value:
            return False
        context["planet_name"] = correction
        return True
