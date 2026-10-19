"""Shared, versionable contracts for evidence used across ExoTrace components.

These models intentionally contain no exoplanet-specific facts or query-routing rules.
They describe provenance and findings in a transport-neutral form so agents and tools can
exchange evidence without depending directly on FAISS, Neo4j, or an LLM SDK.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


def _require_nonempty(value: str, field_name: str) -> None:
    """Reject blank required string values."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _json_object(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    """Validate an object as JSON-compatible and return an independent copy."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping.")
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain only JSON-compatible values.") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must serialize to a JSON object.")
    return decoded


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """A provenance-carrying reference to a source used in an investigation.

    ``evidence_id`` identifies the evidence item within an investigation. ``source_id``
    identifies the underlying record or document in its native corpus. Source metadata is
    preserved as JSON-compatible data, not interpreted as scientific truth by this class.
    """

    evidence_id: str
    source_id: str
    title: str
    excerpt: str
    source_uri: str | None = None
    source_kind: str | None = None
    snapshot_id: str | None = None
    record_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate identity, content, and JSON-safe provenance metadata."""
        for field_name in ("evidence_id", "source_id", "title", "excerpt"):
            _require_nonempty(getattr(self, field_name), field_name)
        for field_name in ("source_uri", "source_kind", "snapshot_id", "record_id"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be None or a non-empty string.")
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the evidence reference."""
        return {
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
            "title": self.title,
            "excerpt": self.excerpt,
            "source_uri": self.source_uri,
            "source_kind": self.source_kind,
            "snapshot_id": self.snapshot_id,
            "record_id": self.record_id,
            "metadata": _json_object(self.metadata, "metadata"),
        }


@dataclass(frozen=True, slots=True)
class Finding:
    """A structured result produced by an agent.

    ``finding_type`` is an extensible label supplied by the producing agent, rather than
    a centrally hardcoded list. Factual findings should cite supporting evidence IDs.
    Non-factual outputs such as plans or questions may have no evidence IDs.
    """

    finding_id: str
    statement: str
    finding_type: str
    evidence_ids: tuple[str, ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the finding identity and normalize collections."""
        for field_name in ("finding_id", "statement", "finding_type"):
            _require_nonempty(getattr(self, field_name), field_name)
        evidence_ids = tuple(self.evidence_ids)
        if any(not isinstance(item, str) or not item.strip() for item in evidence_ids):
            raise ValueError("evidence_ids must contain non-empty strings.")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence_ids cannot contain duplicates.")
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "data", _json_object(self.data, "data"))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the finding."""
        return {
            "finding_id": self.finding_id,
            "statement": self.statement,
            "finding_type": self.finding_type,
            "evidence_ids": list(self.evidence_ids),
            "data": _json_object(self.data, "data"),
        }
