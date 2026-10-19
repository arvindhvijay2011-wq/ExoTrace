"""Contracts and interfaces for tools that ExoTrace agents may invoke."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from exotrace.contracts import EvidenceReference, _json_object, _require_nonempty


class ToolStatus(str, Enum):
    """Outcome of a tool invocation."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Machine-readable description of a tool and its permission boundary."""

    tool_id: str
    name: str
    purpose: str
    capabilities: tuple[str, ...]
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    read_only: bool = True
    version: str = "1.0"
    requires_authentication: bool = False

    def __post_init__(self) -> None:
        """Validate metadata and JSON-schema objects."""
        for field_name in ("tool_id", "name", "purpose", "version"):
            _require_nonempty(getattr(self, field_name), field_name)
        capabilities = tuple(self.capabilities)
        if any(not isinstance(item, str) or not item.strip() for item in capabilities):
            raise ValueError("capabilities must contain non-empty strings.")
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("capabilities cannot contain duplicates.")
        if not isinstance(self.read_only, bool):
            raise TypeError("read_only must be a boolean.")
        if not isinstance(self.requires_authentication, bool):
            raise TypeError("requires_authentication must be a boolean.")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "input_schema", _json_object(self.input_schema, "input_schema"))
        object.__setattr__(self, "output_schema", _json_object(self.output_schema, "output_schema"))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable description suitable for an agent planner."""
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "purpose": self.purpose,
            "capabilities": list(self.capabilities),
            "input_schema": _json_object(self.input_schema, "input_schema"),
            "output_schema": _json_object(self.output_schema, "output_schema"),
            "read_only": self.read_only,
            "version": self.version,
            "requires_authentication": self.requires_authentication,
        }


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """One explicit request to call a registered tool."""

    call_id: str
    tool_id: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate request identity and JSON-compatible arguments."""
        _require_nonempty(self.call_id, "call_id")
        _require_nonempty(self.tool_id, "tool_id")
        object.__setattr__(self, "arguments", _json_object(self.arguments, "arguments"))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable tool request."""
        return {
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "arguments": _json_object(self.arguments, "arguments"),
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Structured output from one tool invocation, including source provenance."""

    call_id: str
    tool_id: str
    status: ToolStatus
    data: Mapping[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceReference, ...] = ()
    message: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        """Validate the result shape and associated evidence identities."""
        _require_nonempty(self.call_id, "call_id")
        _require_nonempty(self.tool_id, "tool_id")
        try:
            status = ToolStatus(self.status)
        except ValueError as exc:
            raise ValueError(f"Unsupported tool status: {self.status!r}.") from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "data", _json_object(self.data, "data"))
        evidence = tuple(self.evidence)
        if not all(isinstance(item, EvidenceReference) for item in evidence):
            raise TypeError("evidence must contain EvidenceReference objects.")
        evidence_ids = [item.evidence_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence must not contain duplicate evidence IDs.")
        object.__setattr__(self, "evidence", evidence)
        for field_name in ("message", "error_code"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be None or a non-empty string.")
        if status is ToolStatus.FAILED and not (self.error_code or self.message):
            raise ValueError("A failed tool result must include error_code or message.")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable tool result."""
        return {
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "status": self.status.value,
            "data": _json_object(self.data, "data"),
            "evidence": [item.to_dict() for item in self.evidence],
            "message": self.message,
            "error_code": self.error_code,
        }


class ExoTraceTool(Protocol):
    """Interface implemented by a concrete, independently testable ExoTrace tool."""

    @property
    def descriptor(self) -> ToolDescriptor:
        """Describe this tool's purpose, schemas, capabilities, and permissions."""
        ...

    def execute(self, request: ToolRequest) -> ToolResult:
        """Execute one validated request and return structured results."""
        ...


class ToolExecutor(Protocol):
    """Restricted interface exposed to an agent during one task."""

    def execute(self, request: ToolRequest) -> ToolResult:
        """Execute a request only if its tool is permitted for the agent and task."""
        ...
