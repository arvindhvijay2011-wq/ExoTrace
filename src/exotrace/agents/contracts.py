"""Typed contracts for ExoTrace specialist agents and their task boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from exotrace.contracts import EvidenceReference, Finding, _json_object, _require_nonempty

if TYPE_CHECKING:
    from exotrace.tools.contracts import ToolExecutor


class AgentStatus(str, Enum):
    """Outcome of a specialist agent's task."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    """A specialist's stable responsibility and explicit tool permissions.

    Capability names are data supplied by each agent implementation. The shared registry
    does not contain a hardcoded list of agent roles or map question keywords to agents.
    """

    agent_id: str
    name: str
    responsibility: str
    capabilities: tuple[str, ...]
    allowed_tool_ids: tuple[str, ...] = ()
    input_schema_version: str = "1.0"
    output_schema_version: str = "1.0"
    task_context_schema: Mapping[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    def __post_init__(self) -> None:
        """Validate identity and normalize capabilities and tool permissions."""
        for field_name in (
            "agent_id",
            "name",
            "responsibility",
            "input_schema_version",
            "output_schema_version",
        ):
            _require_nonempty(getattr(self, field_name), field_name)
        for field_name in ("capabilities", "allowed_tool_ids"):
            items = tuple(getattr(self, field_name))
            if any(not isinstance(item, str) or not item.strip() for item in items):
                raise ValueError(f"{field_name} must contain non-empty strings.")
            if len(set(items)) != len(items):
                raise ValueError(f"{field_name} cannot contain duplicates.")
            object.__setattr__(self, field_name, items)
        context_schema = _json_object(self.task_context_schema, "task_context_schema")
        if context_schema.get("type") != "object":
            raise ValueError("task_context_schema must declare type='object'.")
        if not isinstance(context_schema.get("properties", {}), dict):
            raise ValueError("task_context_schema.properties must be an object.")
        object.__setattr__(self, "task_context_schema", context_schema)

    def to_dict(self) -> dict[str, Any]:
        """Return a planner-facing description without executable code or secrets."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "responsibility": self.responsibility,
            "capabilities": list(self.capabilities),
            "allowed_tool_ids": list(self.allowed_tool_ids),
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
            "task_context_schema": _json_object(
                self.task_context_schema, "task_context_schema"
            ),
        }


@dataclass(frozen=True, slots=True)
class AgentTask:
    """One bounded work item delegated to a single specialist."""

    task_id: str
    question: str
    objective: str
    required_capabilities: tuple[str, ...] = ()
    allowed_tool_ids: tuple[str, ...] = ()
    input_evidence: tuple[EvidenceReference, ...] = ()
    constraints: tuple[str, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate that a task is scoped, transportable, and evidence-safe."""
        for field_name in ("task_id", "question", "objective"):
            _require_nonempty(getattr(self, field_name), field_name)
        for field_name in ("required_capabilities", "allowed_tool_ids", "constraints"):
            items = tuple(getattr(self, field_name))
            if any(not isinstance(item, str) or not item.strip() for item in items):
                raise ValueError(f"{field_name} must contain non-empty strings.")
            if len(set(items)) != len(items):
                raise ValueError(f"{field_name} cannot contain duplicates.")
            object.__setattr__(self, field_name, items)
        evidence = tuple(self.input_evidence)
        if not all(isinstance(item, EvidenceReference) for item in evidence):
            raise TypeError("input_evidence must contain EvidenceReference objects.")
        evidence_ids = [item.evidence_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("input_evidence cannot contain duplicate evidence IDs.")
        object.__setattr__(self, "input_evidence", evidence)
        object.__setattr__(self, "context", _json_object(self.context, "context"))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable task for logging or model transport."""
        return {
            "task_id": self.task_id,
            "question": self.question,
            "objective": self.objective,
            "required_capabilities": list(self.required_capabilities),
            "allowed_tool_ids": list(self.allowed_tool_ids),
            "input_evidence": [item.to_dict() for item in self.input_evidence],
            "constraints": list(self.constraints),
            "context": _json_object(self.context, "context"),
        }


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Structured outcome from one specialist agent for one task."""

    task_id: str
    agent_id: str
    status: AgentStatus
    summary: str
    findings: tuple[Finding, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    gaps: tuple[str, ...] = ()
    tool_ids_used: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize and validate result fields."""
        _require_nonempty(self.task_id, "task_id")
        _require_nonempty(self.agent_id, "agent_id")
        if not isinstance(self.summary, str):
            raise TypeError("summary must be a string.")
        try:
            status = AgentStatus(self.status)
        except ValueError as exc:
            raise ValueError(f"Unsupported agent status: {self.status!r}.") from exc
        object.__setattr__(self, "status", status)
        for field_name in ("findings", "evidence", "gaps", "tool_ids_used"):
            items = tuple(getattr(self, field_name))
            object.__setattr__(self, field_name, items)
        if not all(isinstance(item, Finding) for item in self.findings):
            raise TypeError("findings must contain Finding objects.")
        if not all(isinstance(item, EvidenceReference) for item in self.evidence):
            raise TypeError("evidence must contain EvidenceReference objects.")
        if any(not isinstance(item, str) or not item.strip() for item in self.gaps):
            raise ValueError("gaps must contain non-empty strings.")
        if any(not isinstance(item, str) or not item.strip() for item in self.tool_ids_used):
            raise ValueError("tool_ids_used must contain non-empty strings.")
        if len(set(self.tool_ids_used)) != len(self.tool_ids_used):
            raise ValueError("tool_ids_used cannot contain duplicates.")
        result_evidence_ids = [item.evidence_id for item in self.evidence]
        if len(result_evidence_ids) != len(set(result_evidence_ids)):
            raise ValueError("result evidence cannot contain duplicate evidence IDs.")
        for field_name in ("error_code", "error_message"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be None or a non-empty string.")
        if status is AgentStatus.FAILED and not (self.error_code or self.error_message):
            raise ValueError("A failed agent result must include error_code or error_message.")
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))

    def validate_for(self, task: AgentTask, descriptor: AgentDescriptor) -> None:
        """Raise if the result does not satisfy this task's identity and evidence boundary."""
        if self.task_id != task.task_id:
            raise ValueError("Agent result task_id does not match the assigned task.")
        if self.agent_id != descriptor.agent_id:
            raise ValueError("Agent result agent_id does not match the producing agent.")

        permitted_tools = set(task.allowed_tool_ids) & set(descriptor.allowed_tool_ids)
        unauthorized_tools = sorted(set(self.tool_ids_used) - permitted_tools)
        if unauthorized_tools:
            raise ValueError(
                "Agent result reports tools outside the intersection of task and agent "
                f"permissions: {unauthorized_tools}."
            )

        evidence_by_id = {item.evidence_id: item for item in task.input_evidence}
        for item in self.evidence:
            existing = evidence_by_id.get(item.evidence_id)
            if existing is not None and (
                existing.source_id != item.source_id or existing.excerpt != item.excerpt
            ):
                raise ValueError(
                    f"Evidence ID {item.evidence_id!r} conflicts with an input evidence item."
                )
            evidence_by_id[item.evidence_id] = item

        unknown_ids = sorted(
            {
                evidence_id
                for finding in self.findings
                for evidence_id in finding.evidence_ids
                if evidence_id not in evidence_by_id
            }
        )
        if unknown_ids:
            raise ValueError(f"Findings cite evidence not available to this task: {unknown_ids}.")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result for audit logs or inter-agent handoff."""
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "summary": self.summary,
            "findings": [item.to_dict() for item in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "gaps": list(self.gaps),
            "tool_ids_used": list(self.tool_ids_used),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": _json_object(self.metadata, "metadata"),
        }


class SpecialistAgent(Protocol):
    """Interface implemented by one agent with one declared responsibility."""

    @property
    def descriptor(self) -> AgentDescriptor:
        """Return this agent's stable purpose, capabilities, and tool permissions."""
        ...

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        """Perform the assigned objective using only the injected tool executor."""
        ...
