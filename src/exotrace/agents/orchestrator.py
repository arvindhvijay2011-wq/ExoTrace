"""Bounded orchestration of ExoTrace specialist agents.

Planning is delegated to an injected planner. This module does not inspect question keywords
or maintain an agent-specific routing table. It validates the proposed tasks against the live
agent contracts, assigns least-privilege tool allowlists, executes specialists, and records
structured outcomes with their evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable, Mapping
from uuid import uuid4

from exotrace.agents.contracts import (
    AgentDescriptor,
    AgentResult,
    AgentStatus,
    AgentTask,
)
from exotrace.agents.planning import (
    InvestigationPlan,
    PlanDisposition,
    PlannedAgentTask,
    TaskPlanner,
)
from exotrace.agents.registry import AgentRegistry
from exotrace.contracts import EvidenceReference
from exotrace.tools.registry import ToolRegistry


class OrchestrationError(RuntimeError):
    """Raised when a plan violates the current registry or task contracts."""


class InvestigationStatus(str, Enum):
    """Outcome of a complete planning and specialist-execution run."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"
    PLANNED = "planned"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    """Operational budgets for one investigation run."""

    max_agent_tasks: int = 5

    def __post_init__(self) -> None:
        """Validate the maximum number of delegated specialist tasks."""
        if isinstance(self.max_agent_tasks, bool) or not isinstance(self.max_agent_tasks, int):
            raise TypeError("max_agent_tasks must be an integer.")
        if self.max_agent_tasks < 1:
            raise ValueError("max_agent_tasks must be positive.")


@dataclass(frozen=True, slots=True)
class InvestigationReport:
    """Auditable output from a plan and its specialist results."""

    question: str
    status: InvestigationStatus
    plan: InvestigationPlan
    results: tuple[AgentResult, ...] = ()
    started_at_utc: str = ""
    completed_at_utc: str = ""

    def __post_init__(self) -> None:
        """Check report identity and normalize specialist results."""
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("question must be a non-empty string.")
        if self.plan.question != self.question:
            raise ValueError("report question must match the investigation plan question.")
        try:
            status = InvestigationStatus(self.status)
        except ValueError as exc:
            raise ValueError(f"Unsupported investigation status: {self.status!r}.") from exc
        object.__setattr__(self, "status", status)
        results = tuple(self.results)
        if not all(isinstance(item, AgentResult) for item in results):
            raise TypeError("results must contain AgentResult objects.")
        object.__setattr__(self, "results", results)
        for field_name in ("started_at_utc", "completed_at_utc"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string.")

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready report data, including all agent findings and provenance."""
        return {
            "question": self.question,
            "status": self.status.value,
            "plan": self.plan.to_dict(),
            "results": [item.to_dict() for item in self.results],
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
        }


def validate_context_against_schema(value: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    """Validate the JSON Schema subset used by specialist task-context contracts.

    This small validator covers the schema constructs used by ExoTrace's declared task
    contracts. It fails closed on unknown schema types/keywords instead of pretending to
    implement the full JSON Schema standard.
    """
    _validate_schema_value(value, schema, path="context")


def _validate_schema_value(value: Any, schema: Mapping[str, Any], *, path: str) -> None:
    """Recursively validate supported type, enum, required, and collection constraints."""
    supported_keywords = {
        # JSON Schema annotations describe fields but do not change validation.
        "description",
        "type",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "minProperties",
        "items",
        "minItems",
        "uniqueItems",
        "minLength",
        "minimum",
    }
    unsupported_keywords = set(schema) - supported_keywords
    if unsupported_keywords:
        raise OrchestrationError(
            f"Unsupported schema keyword(s) at {path}: {sorted(unsupported_keywords)}."
        )
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, Mapping):
            raise OrchestrationError(f"{path} must be an object.")
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise OrchestrationError(f"Invalid required list in schema at {path}.")
        missing = sorted(set(required) - set(value))
        if missing:
            raise OrchestrationError(f"{path} is missing required field(s): {missing}.")
        minimum_properties = schema.get("minProperties")
        if minimum_properties is not None and len(value) < minimum_properties:
            raise OrchestrationError(
                f"{path} must contain at least {minimum_properties} properties."
            )
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise OrchestrationError(f"Invalid properties schema at {path}.")
        additional_properties = schema.get("additionalProperties", True)
        unknown = set(value) - set(properties)
        if unknown and additional_properties is False:
            raise OrchestrationError(f"{path} contains unsupported field(s): {sorted(unknown)}.")
        for key, item in value.items():
            if key in properties:
                child_schema = properties[key]
            elif isinstance(additional_properties, Mapping):
                child_schema = additional_properties
            elif additional_properties is True:
                continue
            else:
                raise OrchestrationError(f"{path}.{key} is not allowed by its schema.")
            if not isinstance(child_schema, Mapping):
                raise OrchestrationError(f"Invalid schema for {path}.{key}.")
            _validate_schema_value(item, child_schema, path=f"{path}.{key}")
    elif schema_type == "array":
        if not isinstance(value, list):
            raise OrchestrationError(f"{path} must be an array.")
        minimum_items = schema.get("minItems")
        if minimum_items is not None and len(value) < minimum_items:
            raise OrchestrationError(f"{path} must contain at least {minimum_items} item(s).")
        if schema.get("uniqueItems") is True:
            try:
                serialized = [
                    json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value
                ]
            except (TypeError, ValueError) as exc:
                raise OrchestrationError(f"{path} contains non-JSON items.") from exc
            if len(serialized) != len(set(serialized)):
                raise OrchestrationError(f"{path} must not contain duplicate items.")
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, Mapping):
                raise OrchestrationError(f"Invalid item schema at {path}.")
            for index, item in enumerate(value):
                _validate_schema_value(item, item_schema, path=f"{path}[{index}]")
    elif schema_type == "string":
        if not isinstance(value, str):
            raise OrchestrationError(f"{path} must be a string.")
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(value) < minimum_length:
            raise OrchestrationError(f"{path} must contain at least {minimum_length} character(s).")
    elif schema_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise OrchestrationError(f"{path} must be an integer.")
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise OrchestrationError(f"{path} must be at least {minimum}.")
    elif schema_type == "boolean":
        if not isinstance(value, bool):
            raise OrchestrationError(f"{path} must be a boolean.")
    elif schema_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise OrchestrationError(f"{path} must be a number.")
    elif schema_type is not None:
        raise OrchestrationError(f"Unsupported schema type {schema_type!r} at {path}.")

    enum_values = schema.get("enum")
    if enum_values is not None:
        if not isinstance(enum_values, list):
            raise OrchestrationError(f"Invalid enum schema at {path}.")
        if value not in enum_values:
            raise OrchestrationError(f"{path} value {value!r} is not in the allowed enum.")


def _status_for_plan(plan: InvestigationPlan, *, execute: bool) -> InvestigationStatus | None:
    """Translate a non-executing plan state into the report state, if applicable."""
    if plan.disposition is PlanDisposition.NEEDS_CLARIFICATION:
        return InvestigationStatus.NEEDS_CLARIFICATION
    if plan.disposition is PlanDisposition.UNSUPPORTED:
        return InvestigationStatus.UNSUPPORTED
    if not execute:
        return InvestigationStatus.PLANNED
    return None


class InvestigationOrchestrator:
    """Coordinate registered specialists using dynamic plans and strict contracts."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        planner: TaskPlanner,
        config: OrchestratorConfig | None = None,
        plan_context_resolver: Callable[[InvestigationPlan], InvestigationPlan] | None = None,
    ) -> None:
        """Inject the live registries, planner, and optional source-backed plan resolver."""
        self._agents = agent_registry
        self._tools = tool_registry
        self._planner = planner
        self._config = config or OrchestratorConfig()
        if plan_context_resolver is not None and not callable(plan_context_resolver):
            raise TypeError("plan_context_resolver must be callable when supplied.")
        self._plan_context_resolver = plan_context_resolver

    def agent_descriptor(self, agent_id: str) -> AgentDescriptor:
        """Return a registered specialist descriptor for safe report rendering."""
        return self._agents.get(agent_id).descriptor

    def tool_descriptors(self):
        """Return registered tool descriptors without exposing executable tool instances."""
        return self._tools.descriptors()

    def create_plan(self, question: str) -> InvestigationPlan:
        """Ask the planner for bounded tasks and validate them against current contracts."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question cannot be empty.")
        descriptors = self._agents.descriptors()
        tool_descriptors = self._tools.descriptors()
        plan = self._planner.create_plan(
            question,
            agents=descriptors,
            tools=tool_descriptors,
            max_tasks=self._config.max_agent_tasks,
        )
        if plan.question != question.strip():
            raise OrchestrationError("Planner returned a plan for a different question.")
        # Validate the model's original proposal before applying the optional source-backed
        # identifier correction. The corrected plan is validated again below, so normalization
        # cannot bypass any existing schema, capability, task-budget, or tool-permission checks.
        self._validate_plan(plan)
        if self._plan_context_resolver is not None:
            resolved_plan = self._plan_context_resolver(plan)
            if not isinstance(resolved_plan, InvestigationPlan):
                raise OrchestrationError(
                    "The plan context resolver must return an InvestigationPlan."
                )
            if resolved_plan.question != question.strip():
                raise OrchestrationError(
                    "The plan context resolver returned a plan for a different question."
                )
            if resolved_plan is not plan:
                self._validate_plan(resolved_plan)
            plan = resolved_plan
        return plan

    def investigate(self, question: str, *, execute: bool = True) -> InvestigationReport:
        """Plan specialist work, optionally execute it, and return an audit-ready report."""
        started = datetime.now(UTC).isoformat()
        plan = self.create_plan(question)
        early_status = _status_for_plan(plan, execute=execute)
        if early_status is not None:
            return InvestigationReport(
                question=plan.question,
                status=early_status,
                plan=plan,
                started_at_utc=started,
                completed_at_utc=datetime.now(UTC).isoformat(),
            )
        return self._execute_validated_plan(plan, started_at_utc=started)

    def execute_plan(self, plan: InvestigationPlan) -> InvestigationReport:
        """Execute a previously reviewed plan after revalidating it against live contracts."""
        self._validate_plan(plan)
        started = datetime.now(UTC).isoformat()
        early_status = _status_for_plan(plan, execute=True)
        if early_status is not None:
            return InvestigationReport(
                question=plan.question,
                status=early_status,
                plan=plan,
                started_at_utc=started,
                completed_at_utc=datetime.now(UTC).isoformat(),
            )
        return self._execute_validated_plan(plan, started_at_utc=started)

    def validate_plan(self, plan: InvestigationPlan) -> None:
        """Publicly validate a plan against current agent, tool, schema, and budget contracts."""
        self._validate_plan(plan)

    def execute_planned_task(
        self,
        plan: InvestigationPlan,
        planned_task: PlannedAgentTask,
        *,
        run_id: str,
        task_index: int,
        results_by_task_key: Mapping[str, AgentResult],
        outputs_by_task_key: Mapping[str, tuple[EvidenceReference, ...]],
    ) -> tuple[AgentResult, tuple[EvidenceReference, ...]]:
        """Execute exactly one validated plan task and return its newly produced evidence.

        This method is shared by the legacy sequential executor and the LangGraph per-task
        nodes. It preserves the same task contracts, dependency-only evidence handoff, tool
        permission intersection, result validation, and producer provenance tagging.
        """
        self._validate_plan(plan)
        if plan.disposition is not PlanDisposition.READY:
            raise OrchestrationError("Only READY plans may execute specialist tasks.")
        if not isinstance(planned_task, PlannedAgentTask):
            raise TypeError("planned_task must be a PlannedAgentTask.")
        if isinstance(task_index, bool) or not isinstance(task_index, int):
            raise TypeError("task_index must be an integer.")
        if task_index < 1 or task_index > len(plan.tasks):
            raise ValueError("task_index is outside the plan task range.")
        expected_task = plan.tasks[task_index - 1]
        if expected_task.task_key != planned_task.task_key or expected_task != planned_task:
            raise OrchestrationError(
                "The requested specialist task does not match the task at task_index in the plan."
            )
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string.")
        if not isinstance(results_by_task_key, Mapping):
            raise TypeError("results_by_task_key must be a mapping.")
        if not isinstance(outputs_by_task_key, Mapping):
            raise TypeError("outputs_by_task_key must be a mapping.")

        agent = self._agents.get(planned_task.agent_id)
        descriptor = agent.descriptor
        task_id = f"{run_id}:{task_index}"
        task = AgentTask(
            task_id=task_id,
            question=planned_task.question,
            objective=planned_task.objective,
            required_capabilities=planned_task.required_capabilities,
            allowed_tool_ids=descriptor.allowed_tool_ids,
            input_evidence=(),
            context=planned_task.context,
        )
        produced_evidence: tuple[EvidenceReference, ...] = ()
        try:
            for dependency_key in planned_task.depends_on:
                dependency_result = results_by_task_key.get(dependency_key)
                if dependency_result is None:
                    raise OrchestrationError(
                        f"Dependency task {dependency_key!r} has not completed."
                    )
                if dependency_result.status not in {AgentStatus.SUCCEEDED, AgentStatus.PARTIAL}:
                    raise OrchestrationError(
                        f"Dependency task {dependency_key!r} finished with status "
                        f"{dependency_result.status.value!r}; downstream execution was withheld."
                    )
            input_evidence = self._dependency_evidence(
                planned_task.depends_on,
                outputs_by_task_key,
            )
            task = replace(task, input_evidence=input_evidence)
            executor = self._tools.executor_for(descriptor, task)
            result = agent.run(task, tools=executor)
            if not isinstance(result, AgentResult):
                raise TypeError(
                    f"Agent returned {type(result).__name__}; expected AgentResult."
                )
            result.validate_for(task, descriptor)
            result, produced_evidence = self._tag_task_outputs(
                result,
                input_evidence=input_evidence,
                task_key=planned_task.task_key,
                agent_id=descriptor.agent_id,
            )
            result.validate_for(task, descriptor)
        except Exception as exc:
            result = AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary=(
                    "The specialist task failed during validation, dependency handoff, or execution."
                ),
                error_code="specialist_task_failed",
                error_message=f"{type(exc).__name__}: {exc}",
                metadata={
                    "task_objective": task.objective,
                    "task_key": planned_task.task_key,
                    "depends_on": list(planned_task.depends_on),
                },
            )
            produced_evidence = ()
        return result, produced_evidence

    def report_from_task_results(
        self,
        plan: InvestigationPlan,
        results_by_task_key: Mapping[str, AgentResult],
        *,
        started_at_utc: str,
        completed_at_utc: str | None = None,
    ) -> InvestigationReport:
        """Build an ordered investigation report from completed native task-node results."""
        self._validate_plan(plan)
        if plan.disposition is not PlanDisposition.READY:
            raise OrchestrationError("Task results can only complete a READY plan.")
        if not isinstance(results_by_task_key, Mapping):
            raise TypeError("results_by_task_key must be a mapping.")
        expected_keys = {item.task_key for item in plan.tasks}
        supplied_keys = set(results_by_task_key)
        missing = sorted(expected_keys - supplied_keys)
        unexpected = sorted(supplied_keys - expected_keys)
        if missing or unexpected:
            raise OrchestrationError(
                f"Task result set does not match plan; missing={missing}, unexpected={unexpected}."
            )
        ordered_results = [results_by_task_key[item.task_key] for item in plan.tasks]
        if not all(isinstance(item, AgentResult) for item in ordered_results):
            raise TypeError("Every task result must be an AgentResult.")
        return InvestigationReport(
            question=plan.question,
            status=self._aggregate_status(ordered_results),
            plan=plan,
            results=tuple(ordered_results),
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc or datetime.now(UTC).isoformat(),
        )

    def _execute_validated_plan(
        self,
        plan: InvestigationPlan,
        *,
        started_at_utc: str,
    ) -> InvestigationReport:
        """Execute tasks sequentially using the same single-task boundary as LangGraph."""
        run_id = uuid4().hex
        outputs_by_task_key: dict[str, tuple[EvidenceReference, ...]] = {}
        results_by_task_key: dict[str, AgentResult] = {}

        for index, planned_task in enumerate(plan.tasks, start=1):
            result, produced_evidence = self.execute_planned_task(
                plan,
                planned_task,
                run_id=run_id,
                task_index=index,
                results_by_task_key=results_by_task_key,
                outputs_by_task_key=outputs_by_task_key,
            )
            outputs_by_task_key[planned_task.task_key] = produced_evidence
            results_by_task_key[planned_task.task_key] = result

        return self.report_from_task_results(
            plan,
            results_by_task_key,
            started_at_utc=started_at_utc,
        )

    @staticmethod
    def _dependency_evidence(
        dependency_keys: tuple[str, ...],
        outputs_by_task_key: Mapping[str, tuple[EvidenceReference, ...]],
    ) -> tuple[EvidenceReference, ...]:
        """Collect only fresh evidence from explicit dependencies, rejecting ID collisions."""
        combined: dict[str, EvidenceReference] = {}
        for dependency_key in dependency_keys:
            if dependency_key not in outputs_by_task_key:
                raise OrchestrationError(
                    f"Dependency task {dependency_key!r} has not produced an execution result."
                )
            for evidence in outputs_by_task_key[dependency_key]:
                existing = combined.get(evidence.evidence_id)
                if existing is not None:
                    if existing.source_id != evidence.source_id or existing.excerpt != evidence.excerpt:
                        raise OrchestrationError(
                            f"Dependency evidence ID {evidence.evidence_id!r} refers to conflicting sources."
                        )
                    existing_producer = existing.metadata.get("exotrace_producer_task_key")
                    incoming_producer = evidence.metadata.get("exotrace_producer_task_key")
                    if existing_producer != incoming_producer:
                        raise OrchestrationError(
                            f"Dependency evidence ID {evidence.evidence_id!r} was produced by "
                            "multiple task keys; make the dependencies unambiguous."
                        )
                    continue
                combined[evidence.evidence_id] = evidence
        return tuple(combined.values())

    @staticmethod
    def _tag_task_outputs(
        result: AgentResult,
        *,
        input_evidence: tuple[EvidenceReference, ...],
        task_key: str,
        agent_id: str,
    ) -> tuple[AgentResult, tuple[EvidenceReference, ...]]:
        """Annotate newly produced evidence with its producing task and agent IDs."""
        input_ids = {item.evidence_id for item in input_evidence}
        tagged_by_id: dict[str, EvidenceReference] = {}
        for item in result.evidence:
            if item.evidence_id in input_ids:
                continue
            metadata = dict(item.metadata)
            previous_task_key = metadata.get("exotrace_producer_task_key")
            if previous_task_key and previous_task_key != task_key:
                raise OrchestrationError(
                    f"New output evidence {item.evidence_id!r} claims a different producer task."
                )
            metadata["exotrace_producer_task_key"] = task_key
            metadata["exotrace_producer_agent_id"] = agent_id
            tagged_by_id[item.evidence_id] = EvidenceReference(
                evidence_id=item.evidence_id,
                source_id=item.source_id,
                title=item.title,
                excerpt=item.excerpt,
                source_uri=item.source_uri,
                source_kind=item.source_kind,
                snapshot_id=item.snapshot_id,
                record_id=item.record_id,
                metadata=metadata,
            )
        if result.status not in {AgentStatus.SUCCEEDED, AgentStatus.PARTIAL}:
            tagged_by_id = {}
        updated_evidence = tuple(
            item if item.evidence_id in input_ids else tagged_by_id.get(item.evidence_id, item)
            for item in result.evidence
        )
        updated_result = replace(result, evidence=updated_evidence)
        return updated_result, tuple(tagged_by_id.values())

    def _validate_plan(self, plan: InvestigationPlan) -> None:
        """Reject unknown agents, unsupported capabilities, bad contexts, and excess work."""
        if not isinstance(plan, InvestigationPlan):
            raise TypeError("plan must be an InvestigationPlan.")
        if len(plan.tasks) > self._config.max_agent_tasks:
            raise OrchestrationError(
                f"Plan has {len(plan.tasks)} tasks; configured maximum is "
                f"{self._config.max_agent_tasks}."
            )
        descriptors = {item.agent_id: item for item in self._agents.descriptors()}
        tool_ids = {item.tool_id for item in self._tools.descriptors()}
        for index, planned_task in enumerate(plan.tasks, start=1):
            try:
                descriptor: AgentDescriptor = descriptors[planned_task.agent_id]
            except KeyError as exc:
                raise OrchestrationError(
                    f"Plan task {index} names unregistered agent {planned_task.agent_id!r}."
                ) from exc
            if not planned_task.required_capabilities:
                raise OrchestrationError(
                    f"Plan task {index} must declare at least one required capability."
                )
            missing_capabilities = sorted(
                set(planned_task.required_capabilities) - set(descriptor.capabilities)
            )
            if missing_capabilities:
                raise OrchestrationError(
                    f"Plan task {index} requests undeclared capability/capabilities from "
                    f"{descriptor.agent_id!r}: {missing_capabilities}."
                )
            if not descriptor.allowed_tool_ids:
                raise OrchestrationError(
                    f"Agent {descriptor.agent_id!r} has no explicitly permitted tools."
                )
            missing_tools = sorted(set(descriptor.allowed_tool_ids) - tool_ids)
            if missing_tools:
                raise OrchestrationError(
                    f"Agent {descriptor.agent_id!r} grants unregistered tools: {missing_tools}."
                )
            validate_context_against_schema(
                planned_task.context,
                descriptor.task_context_schema,
            )

    @staticmethod
    def _aggregate_status(results: list[AgentResult]) -> InvestigationStatus:
        """Aggregate specialist outcomes without masking partial failures."""
        if not results:
            return InvestigationStatus.FAILED
        statuses = [item.status for item in results]
        if all(item is AgentStatus.SUCCEEDED for item in statuses):
            return InvestigationStatus.COMPLETED
        if all(item is AgentStatus.INSUFFICIENT_EVIDENCE for item in statuses):
            return InvestigationStatus.INSUFFICIENT_EVIDENCE
        if all(item is AgentStatus.FAILED for item in statuses):
            return InvestigationStatus.FAILED
        if any(item in {AgentStatus.SUCCEEDED, AgentStatus.PARTIAL} for item in statuses):
            return InvestigationStatus.PARTIAL
        return InvestigationStatus.PARTIAL
