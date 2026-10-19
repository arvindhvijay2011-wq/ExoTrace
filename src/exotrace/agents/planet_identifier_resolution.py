"""Resolve planner-shortened planet identifiers only from explicit catalogue evidence.

The resolver does not infer a planet from keywords or search for arbitrary aliases. It looks for
complete, canonical ``pl_name`` values literally present in the user's question, using identities
from the checksum-verified catalogue. A shortened task identifier is repaired only when it equals
the hostname of exactly one such explicitly mentioned planet. Ambiguous and host-star operations
are left unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Mapping

from exotrace.agents.planning import InvestigationPlan, PlanDisposition, PlannedAgentTask


class CataloguePlanetIdentifierResolver:
    """Safely align planner contexts with complete planet names explicitly in the question."""

    def __init__(self, planet_host_identities: Sequence[tuple[str, str]]) -> None:
        """Create a resolver from canonical ``(pl_name, hostname)`` source pairs."""
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
        if plan.disposition is not PlanDisposition.READY:
            return plan

        mentioned = self._explicitly_mentioned_planets(plan.question)
        if not mentioned:
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
