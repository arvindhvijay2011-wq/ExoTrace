"""Resolve planner identifiers and safe broad-profile defaults from catalogue evidence.

Canonical ``pl_name`` and hostname identities come from the checksum-verified catalogue. A
shortened task identifier is repaired only when the complete planet name is explicit in the
question and uniquely resolves to the supplied hostname. When a planner asks only for a preferred
level of detail despite one uniquely named planet, the application can create a broad profile from
live catalogue, graph, and reference-agent contracts. Ambiguous identities and host-star operations
are left unchanged.
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
        include_context_sources: bool = False,
        max_agent_tasks: int = 5,
    ) -> None:
        """Create a resolver from verified identities and optional live agent contracts.

        ``include_context_sources`` opts the application into broad-profile source completion.
        It defaults to false for compatibility with existing consumers that rely on the original
        catalogue-only fallback. Candidate graph/reference specialists are selected by their
        declared capabilities and schemas, never by question keywords or planet-specific rules.
        """
        if any(not isinstance(item, AgentDescriptor) for item in agent_descriptors):
            raise TypeError("agent_descriptors must contain AgentDescriptor objects.")
        if not isinstance(include_context_sources, bool):
            raise TypeError("include_context_sources must be a boolean.")
        if isinstance(max_agent_tasks, bool) or not isinstance(max_agent_tasks, int):
            raise TypeError("max_agent_tasks must be an integer.")
        if max_agent_tasks < 1:
            raise ValueError("max_agent_tasks must be positive.")
        self._agent_descriptors = tuple(agent_descriptors)
        self._include_context_sources = include_context_sources
        self._max_agent_tasks = max_agent_tasks
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

        resolved_plan = replace(plan, tasks=tuple(resolved_tasks)) if changed else plan
        if self._include_context_sources and len(mentioned) == 1:
            resolved_plan = self._complete_broad_profile_sources(resolved_plan, mentioned[0][0])
        return resolved_plan

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
        catalogue_task = PlannedAgentTask(
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
        tasks: tuple[PlannedAgentTask, ...] = (catalogue_task,)
        if self._include_context_sources:
            additions = self._build_context_source_tasks(
                question=plan.question,
                planet_name=planet_name,
                existing_tasks=tasks,
            )
            # The configured task budget is a contract. If the complete default profile does not
            # fit, preserve the original clarification outcome rather than silently exceed it.
            if additions is None:
                return plan
            tasks = (*tasks, *additions)

        task_names = [self._descriptor_for_task(task).name for task in tasks]
        summary = (
            "The question identifies one canonical planet in the validated catalogue. "
            "Using the broad catalogue profile as the default avoids asking the user to choose "
            "among optional information categories."
        )
        if len(tasks) > 1:
            summary += " Complementary source retrieval is assigned to: " + ", ".join(
                task_names[1:]
            ) + "."

        return InvestigationPlan(
            question=plan.question,
            disposition=PlanDisposition.READY,
            summary=summary,
            tasks=tasks,
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

    def _complete_broad_profile_sources(
        self,
        plan: InvestigationPlan,
        planet_name: str,
    ) -> InvestigationPlan:
        """Add available graph/reference retrieval to a broad catalogue-profile plan.

        A catalogue task is considered broad only when its structured filter targets this exact
        canonical ``pl_name`` and no explicit ``fields`` restriction was supplied. This decision
        comes from the live task context, not natural-language keyword routing. Narrow catalogue
        queries, multi-planet questions, and plans without a broad catalogue task remain unchanged.
        """
        if not self._has_broad_catalogue_profile_task(plan.tasks, planet_name):
            return plan
        additions = self._build_context_source_tasks(
            question=plan.question,
            planet_name=planet_name,
            existing_tasks=plan.tasks,
        )
        if not additions:
            return plan
        updated_tasks = (*plan.tasks, *additions)
        if len(updated_tasks) > self._max_agent_tasks:
            return plan
        source_names = [self._descriptor_for_task(task).name for task in additions]
        summary = plan.summary.rstrip()
        if summary:
            summary += " "
        summary += (
            "The broad catalogue profile is supplemented with complementary source retrieval "
            "from: " + ", ".join(source_names) + "."
        )
        return replace(plan, tasks=updated_tasks, summary=summary)

    def _has_broad_catalogue_profile_task(
        self,
        tasks: Sequence[PlannedAgentTask],
        planet_name: str,
    ) -> bool:
        """Check that a task explicitly requests a canonical planet without a field restriction."""
        descriptor = self._catalogue_profile_descriptor()
        if descriptor is None:
            return False
        target = planet_name.casefold()
        for task in tasks:
            if task.agent_id != descriptor.agent_id or "fields" in task.context:
                continue
            filters = task.context.get("filters")
            if isinstance(filters, Mapping):
                value = filters.get("pl_name")
                if isinstance(value, str) and value.strip().casefold() == target:
                    return True
            elif isinstance(filters, list):
                for clause in filters:
                    if not isinstance(clause, Mapping):
                        continue
                    value = clause.get("value")
                    if (
                        clause.get("field") == "pl_name"
                        and isinstance(value, str)
                        and value.strip().casefold() == target
                    ):
                        return True
        return False

    def _build_context_source_tasks(
        self,
        *,
        question: str,
        planet_name: str,
        existing_tasks: Sequence[PlannedAgentTask],
    ) -> tuple[PlannedAgentTask, ...] | None:
        """Build extra graph and vector tasks from unique registered contracts.

        The method never makes direct tool calls. It chooses only agents that uniquely expose the
        required capabilities and a compatible declared context schema; the orchestrator still
        validates every returned task and applies the normal tool allowlists before execution.
        ``None`` means the complete set of uniquely available additions exceeds the task budget.
        """
        additions: list[PlannedAgentTask] = []
        existing_ids = {task.agent_id for task in existing_tasks}
        existing_descriptors = [
            descriptor
            for descriptor in self._agent_descriptors
            if descriptor.agent_id in existing_ids
        ]

        graph_requirements = {"graph.read", "graph.relationships"}
        graph_descriptor = self._unique_descriptor_with_capabilities(graph_requirements)
        graph_already_planned = any(
            graph_requirements.issubset(set(item.capabilities))
            for item in existing_descriptors
        )
        if graph_descriptor is not None and not graph_already_planned:
            graph_context = self._planet_context_task_context(graph_descriptor, planet_name)
            if graph_context is not None:
                additions.append(
                    PlannedAgentTask(
                        agent_id=graph_descriptor.agent_id,
                        question=question,
                        objective=(
                            "Retrieve source-backed graph relationships and provenance for the "
                            "explicitly identified planet, including its host and discovery "
                            "context where those relationships are present."
                        ),
                        required_capabilities=graph_descriptor.capabilities,
                        context=graph_context,
                        task_key=self._unique_task_key(
                            "source-graph-context", existing_tasks, additions
                        ),
                        depends_on=(),
                    )
                )

        reference_requirements = {"literature.retrieve", "source.reference_search"}
        reference_descriptor = self._unique_descriptor_with_capabilities(reference_requirements)
        reference_already_planned = any(
            reference_requirements.issubset(set(item.capabilities))
            for item in existing_descriptors
        )
        if reference_descriptor is not None and not reference_already_planned:
            if self._context_accepts_empty_object(reference_descriptor):
                additions.append(
                    PlannedAgentTask(
                        agent_id=reference_descriptor.agent_id,
                        question=question,
                        objective=(
                            "Retrieve relevant passages and source-derived parameter definitions "
                            "from the configured frozen reference corpus to help contextualize "
                            "the explicitly identified planet's catalogue profile. Treat general "
                            "documentation as context, not as a planet-specific publication."
                        ),
                        required_capabilities=reference_descriptor.capabilities,
                        context={},
                        task_key=self._unique_task_key(
                            "source-reference-context", existing_tasks, additions
                        ),
                        depends_on=(),
                    )
                )

        if len(existing_tasks) + len(additions) > self._max_agent_tasks:
            return None
        return tuple(additions)

    def _unique_descriptor_with_capabilities(
        self,
        required_capabilities: set[str],
    ) -> AgentDescriptor | None:
        """Return a uniquely registered descriptor declaring every requested capability."""
        candidates = [
            descriptor
            for descriptor in self._agent_descriptors
            if required_capabilities.issubset(set(descriptor.capabilities))
        ]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _planet_context_task_context(
        descriptor: AgentDescriptor,
        planet_name: str,
    ) -> dict[str, Any] | None:
        """Construct graph context only when its live schema supports the required operation."""
        schema = descriptor.task_context_schema
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return None
        operation_schema = properties.get("operation")
        planet_schema = properties.get("planet_name")
        if not isinstance(operation_schema, Mapping) or not isinstance(planet_schema, Mapping):
            return None
        operation_values = operation_schema.get("enum")
        if (
            operation_schema.get("type") != "string"
            or not isinstance(operation_values, list)
            or "planet_context" not in operation_values
        ):
            return None
        if planet_schema.get("type") != "string":
            return None
        required = set(schema.get("required", []))
        if not {"operation"}.issubset(required):
            return None
        return {"operation": "planet_context", "planet_name": planet_name}

    @staticmethod
    def _context_accepts_empty_object(descriptor: AgentDescriptor) -> bool:
        """Check whether the registered context schema permits the default empty context."""
        schema = descriptor.task_context_schema
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        return (
            isinstance(required, list)
            and not required
            and isinstance(properties, Mapping)
            and schema.get("type") == "object"
        )

    def _descriptor_for_task(self, task: PlannedAgentTask) -> AgentDescriptor:
        """Return the live descriptor for a task already built from registered contracts."""
        for descriptor in self._agent_descriptors:
            if descriptor.agent_id == task.agent_id:
                return descriptor
        # All tasks produced here are built from validated descriptors. This is a defensive
        # guard in case a caller constructs a resolver and descriptor list inconsistently.
        raise ValueError(f"No registered descriptor for task agent {task.agent_id!r}.")

    @staticmethod
    def _unique_task_key(
        base: str,
        existing_tasks: Sequence[PlannedAgentTask],
        additions: Sequence[PlannedAgentTask],
    ) -> str:
        """Create a unique stable task key without disturbing existing caller-supplied keys."""
        used = {task.task_key for task in (*existing_tasks, *additions)}
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

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
