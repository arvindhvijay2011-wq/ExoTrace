"""Read-only, provenance-preserving investigations of the ExoTrace Neo4j graph.

Only fixed, parameterized Cypher templates defined in this module may run. Callers choose
among named operations and supply entity identifiers; they cannot submit Cypher, choose
labels/relationship types, or modify the database.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib.parse import urlparse

from exotrace.contracts import EvidenceReference
from exotrace.tools.contracts import ToolDescriptor, ToolRequest, ToolResult, ToolStatus


class Neo4jTransaction(Protocol):
    """Structural subset of a Neo4j transaction used by this read-only tool."""

    def run(self, query: str, **parameters: Any) -> Iterable[Mapping[str, Any]]:
        """Execute a parameterized, read-only Cypher statement."""
        ...


class Neo4jReadSession(Protocol):
    """Structural subset of a Neo4j session required for managed read transactions."""

    def __enter__(self) -> Neo4jReadSession:
        ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        ...

    def execute_read(
        self,
        work: Callable[[Neo4jTransaction], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Run work in a read transaction and return its result."""
        ...


class Neo4jDriver(Protocol):
    """Structural subset of an authenticated Neo4j driver."""

    def session(self, *, database: str) -> Neo4jReadSession:
        """Open a session scoped to one configured database."""
        ...


@dataclass(frozen=True, slots=True)
class GraphInvestigationConfig:
    """Configurable execution limits for the graph investigation tool."""

    database: str = "exotrace"
    default_result_limit: int = 25
    max_result_limit: int = 100

    def __post_init__(self) -> None:
        """Validate the database name and result budget."""
        if not isinstance(self.database, str) or not self.database.strip():
            raise ValueError("database must be a non-empty string.")
        for name in ("default_result_limit", "max_result_limit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer.")
            if value < 1:
                raise ValueError(f"{name} must be positive.")
        if self.max_result_limit < self.default_result_limit:
            raise ValueError("max_result_limit must be at least default_result_limit.")


# These are deliberately fixed, read-only Cypher operations over the imported graph schema.
# User and model values are bound as parameters, never interpolated into query text.
_PLANET_CONTEXT_QUERY = """
/* ExoTrace operation: planet_context */
OPTIONAL MATCH (planet:Planet {name: $planet_name})
CALL {
    WITH planet
    OPTIONAL MATCH (host:HostStar)-[rel:HOSTS]->(planet)
    WITH DISTINCT host.name AS name, rel.snapshot_id AS snapshot_id,
         rel.source_record_id AS source_record_id
    ORDER BY name, snapshot_id, source_record_id
    WITH collect(CASE WHEN name IS NULL THEN null ELSE {
        name: name, snapshot_id: snapshot_id, source_record_id: source_record_id
    } END) AS items
    RETURN size(items) AS host_count, items[0..$result_limit] AS host_stars
}
CALL {
    WITH planet
    OPTIONAL MATCH (planet)-[rel:DETECTED_BY]->(method:DiscoveryMethod)
    WITH DISTINCT method.name AS name, rel.snapshot_id AS snapshot_id,
         rel.source_record_id AS source_record_id
    ORDER BY name, snapshot_id, source_record_id
    WITH collect(CASE WHEN name IS NULL THEN null ELSE {
        name: name, snapshot_id: snapshot_id, source_record_id: source_record_id
    } END) AS items
    RETURN size(items) AS discovery_method_count,
           items[0..$result_limit] AS discovery_methods
}
CALL {
    WITH planet
    OPTIONAL MATCH (planet)-[rel:DISCOVERED_AT]->(facility:DiscoveryFacility)
    WITH DISTINCT facility.name AS name, rel.snapshot_id AS snapshot_id,
         rel.source_record_id AS source_record_id
    ORDER BY name, snapshot_id, source_record_id
    WITH collect(CASE WHEN name IS NULL THEN null ELSE {
        name: name, snapshot_id: snapshot_id, source_record_id: source_record_id
    } END) AS items
    RETURN size(items) AS discovery_facility_count,
           items[0..$result_limit] AS discovery_facilities
}
CALL {
    WITH planet
    OPTIONAL MATCH (planet)-[rel:HAS_DISCOVERY_REFERENCE]->(reference:PublicationReference)
    WITH DISTINCT reference.reference_id AS reference_id,
         reference.display_name AS display_name, reference.href AS href,
         rel.snapshot_id AS snapshot_id, rel.source_record_id AS source_record_id
    ORDER BY reference_id, snapshot_id, source_record_id
    WITH collect(CASE WHEN reference_id IS NULL THEN null ELSE {
        reference_id: reference_id, display_name: display_name, href: href,
        snapshot_id: snapshot_id, source_record_id: source_record_id
    } END) AS items
    RETURN size(items) AS discovery_reference_count,
           items[0..$result_limit] AS discovery_references
}
CALL {
    WITH planet
    OPTIONAL MATCH (record:CatalogueRecord)-[:DESCRIBES_PLANET]->(planet)
    WITH DISTINCT record.record_id AS record_id, record.snapshot_id AS snapshot_id,
         record.source_file AS source_file, record.source_row_number AS source_row_number,
         record.hostname AS hostname
    ORDER BY snapshot_id, record_id
    WITH collect(CASE WHEN record_id IS NULL THEN null ELSE {
        record_id: record_id, snapshot_id: snapshot_id, source_file: source_file,
        source_row_number: source_row_number, hostname: hostname
    } END) AS items
    RETURN size(items) AS catalogue_record_count,
           items[0..$result_limit] AS catalogue_records
}
RETURN planet.name AS entity_name,
       planet IS NOT NULL AS entity_found,
       host_stars, host_count,
       discovery_methods, discovery_method_count,
       discovery_facilities, discovery_facility_count,
       discovery_references, discovery_reference_count,
       catalogue_records, catalogue_record_count
"""

_HOST_PLANETS_QUERY = """
/* ExoTrace operation: host_planets */
OPTIONAL MATCH (host:HostStar {name: $host_name})
CALL {
    WITH host
    OPTIONAL MATCH (host)-[rel:HOSTS]->(planet:Planet)
    WITH DISTINCT planet.name AS planet_name, rel.snapshot_id AS snapshot_id,
         rel.source_record_id AS source_record_id
    ORDER BY planet_name, snapshot_id, source_record_id
    WITH collect(CASE WHEN planet_name IS NULL THEN null ELSE {
        planet_name: planet_name, snapshot_id: snapshot_id,
        source_record_id: source_record_id
    } END) AS items
    RETURN size(items) AS planet_count, items[0..$result_limit] AS related_planets
}
RETURN host.name AS entity_name, host IS NOT NULL AS entity_found,
       related_planets, planet_count
"""

_PLANET_RECORDS_QUERY = """
/* ExoTrace operation: planet_records */
OPTIONAL MATCH (planet:Planet {name: $planet_name})
CALL {
    WITH planet
    OPTIONAL MATCH (record:CatalogueRecord)-[:DESCRIBES_PLANET]->(planet)
    WITH DISTINCT record.record_id AS record_id, record.snapshot_id AS snapshot_id,
         record.source_file AS source_file, record.source_row_number AS source_row_number,
         record.hostname AS hostname
    ORDER BY snapshot_id, record_id
    WITH collect(CASE WHEN record_id IS NULL THEN null ELSE {
        record_id: record_id, snapshot_id: snapshot_id, source_file: source_file,
        source_row_number: source_row_number, hostname: hostname
    } END) AS items
    RETURN size(items) AS record_count, items[0..$result_limit] AS catalogue_records
}
RETURN planet.name AS entity_name, planet IS NOT NULL AS entity_found,
       catalogue_records, record_count
"""

_OPERATION_QUERIES: dict[str, str] = {
    "planet_context": _PLANET_CONTEXT_QUERY,
    "host_planets": _HOST_PLANETS_QUERY,
    "planet_records": _PLANET_RECORDS_QUERY,
}

_GROUP_CONTRACTS: dict[str, dict[str, dict[str, str]]] = {
    "planet_context": {
        "host_stars": {
            "count_key": "host_count",
            "relationship_type": "HOSTS",
            "subject_kind": "host_star",
            "object_kind": "planet",
        },
        "discovery_methods": {
            "count_key": "discovery_method_count",
            "relationship_type": "DETECTED_BY",
            "subject_kind": "planet",
            "object_kind": "discovery_method",
        },
        "discovery_facilities": {
            "count_key": "discovery_facility_count",
            "relationship_type": "DISCOVERED_AT",
            "subject_kind": "planet",
            "object_kind": "discovery_facility",
        },
        "discovery_references": {
            "count_key": "discovery_reference_count",
            "relationship_type": "HAS_DISCOVERY_REFERENCE",
            "subject_kind": "planet",
            "object_kind": "publication_reference",
        },
        "catalogue_records": {
            "count_key": "catalogue_record_count",
            "relationship_type": "DESCRIBES_PLANET",
            "subject_kind": "catalogue_record",
            "object_kind": "planet",
        },
    },
    "host_planets": {
        "related_planets": {
            "count_key": "planet_count",
            "relationship_type": "HOSTS",
            "subject_kind": "host_star",
            "object_kind": "planet",
        },
    },
    "planet_records": {
        "catalogue_records": {
            "count_key": "record_count",
            "relationship_type": "DESCRIBES_PLANET",
            "subject_kind": "catalogue_record",
            "object_kind": "planet",
        },
    },
}


class GraphInvestigationTool:
    """Run named, fixed graph reads and return source-record-backed relationships."""

    TOOL_ID = "graph.investigate"
    SUPPORTED_OPERATIONS = tuple(_OPERATION_QUERIES)

    def __init__(
        self,
        driver: Neo4jDriver,
        *,
        config: GraphInvestigationConfig | None = None,
    ) -> None:
        """Use an already-authenticated driver; this class does not own or close it."""
        self._driver = driver
        self._config = config or GraphInvestigationConfig()

    @property
    def descriptor(self) -> ToolDescriptor:
        """Return a machine-readable schema for the safe, named investigation operations."""
        return ToolDescriptor(
            tool_id=self.TOOL_ID,
            name="Read-only graph investigation",
            purpose=(
                "Investigate fixed relationships in the ExoTrace Neo4j graph. The caller can "
                "choose a named operation and entity identifier, but cannot submit Cypher or "
                "select arbitrary labels or relationship types. Every factual result must "
                "retain source-record and snapshot provenance."
            ),
            capabilities=("graph.read", "graph.relationships", "source.provenance"),
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": list(self.SUPPORTED_OPERATIONS),
                    },
                    "planet_name": {"type": "string", "minLength": 1},
                    "host_name": {"type": "string", "minLength": 1},
                    "result_limit": {"type": "integer", "minimum": 1},
                },
                "required": ["operation"],
                "additionalProperties": False,
                "description": (
                    "Use planet_name for planet_context and planet_records; use host_name "
                    "for host_planets."
                ),
            },
            output_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "entity_name": {"type": ["string", "null"]},
                    "entity_found": {"type": "boolean"},
                    "groups": {"type": "object"},
                    "graph_facts": {"type": "array"},
                    "truncated": {"type": "boolean"},
                },
            },
            read_only=True,
            requires_authentication=True,
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        """Validate an operation, execute a read transaction, and attach provenance."""
        if request.tool_id != self.TOOL_ID:
            return self._failure(request, "wrong_tool_id", "Request tool ID does not match.")

        arguments = dict(request.arguments)
        unsupported = sorted(
            set(arguments) - {"operation", "planet_name", "host_name", "result_limit"}
        )
        if unsupported:
            return self._failure(
                request,
                "unsupported_arguments",
                f"Unsupported graph investigation arguments: {unsupported}.",
            )

        operation = arguments.get("operation")
        if not isinstance(operation, str) or operation not in _OPERATION_QUERIES:
            return self._failure(
                request,
                "unsupported_operation",
                f"operation must be one of {list(self.SUPPORTED_OPERATIONS)}.",
            )

        entity_key = "host_name" if operation == "host_planets" else "planet_name"
        entity_name = arguments.get(entity_key)
        if not isinstance(entity_name, str) or not entity_name.strip():
            return self._failure(
                request,
                "missing_entity_name",
                f"A non-empty {entity_key} is required for operation {operation!r}.",
            )
        if "host_name" in arguments and operation != "host_planets":
            return self._failure(
                request,
                "unexpected_entity_argument",
                "host_name is only valid for the host_planets operation.",
            )
        if "planet_name" in arguments and operation == "host_planets":
            return self._failure(
                request,
                "unexpected_entity_argument",
                "planet_name is not valid for the host_planets operation.",
            )

        limit = arguments.get("result_limit", self._config.default_result_limit)
        if isinstance(limit, bool) or not isinstance(limit, int):
            return self._failure(
                request, "invalid_result_limit", "result_limit must be an integer."
            )
        if limit < 1 or limit > self._config.max_result_limit:
            return self._failure(
                request,
                "invalid_result_limit",
                f"result_limit must be between 1 and {self._config.max_result_limit}.",
            )

        parameters = {entity_key: entity_name.strip(), "result_limit": limit}
        query = _OPERATION_QUERIES[operation]
        try:
            with self._driver.session(database=self._config.database) as session:
                rows = session.execute_read(
                    lambda transaction: [
                        dict(record) for record in transaction.run(query, **parameters)
                    ]
                )
        except Exception as exc:  # A tool boundary must return a structured error, not a traceback.
            return self._failure(
                request,
                "graph_read_failed",
                f"Neo4j read operation failed ({type(exc).__name__}). "
                "Check the configured database connection and server logs.",
            )

        if not rows:
            return ToolResult(
                call_id=request.call_id,
                tool_id=request.tool_id,
                status=ToolStatus.PARTIAL,
                data={
                    "operation": operation,
                    "entity_name": entity_name.strip(),
                    "entity_found": False,
                    "groups": {},
                    "graph_facts": [],
                    "truncated": False,
                },
                message=(
                    "The graph query returned no rows, so no relationship evidence is available."
                ),
            )

        row = rows[0]
        entity_found = bool(row.get("entity_found"))
        resolved_name = row.get("entity_name")
        groups: dict[str, Any] = {}
        facts: list[dict[str, Any]] = []
        evidence: list[EvidenceReference] = []
        seen_evidence: set[str] = set()
        missing_provenance = 0
        truncated = False

        for group_name, group_contract in _GROUP_CONTRACTS[operation].items():
            raw_items = row.get(group_name, [])
            items = raw_items if isinstance(raw_items, list) else []
            count_value = row.get(group_contract["count_key"], len(items))
            total_count = (
                count_value
                if isinstance(count_value, int) and count_value >= 0
                else len(items)
            )
            group_truncated = total_count > len(items)
            truncated = truncated or group_truncated
            groups[group_name] = {
                "items": items,
                "total_count": total_count,
                "returned_count": len(items),
                "truncated": group_truncated,
            }
            for item in items:
                if not isinstance(item, Mapping):
                    missing_provenance += 1
                    continue
                evidence_ref, fact = self._make_evidence_and_fact(
                    operation=operation,
                    group_name=group_name,
                    item=dict(item),
                    contract=group_contract,
                    entity_name=str(resolved_name or entity_name.strip()),
                    seen_evidence=seen_evidence,
                )
                if evidence_ref is None or fact is None:
                    missing_provenance += 1
                    continue
                evidence.append(evidence_ref)
                facts.append(fact)

        is_partial = truncated or missing_provenance > 0
        if not entity_found:
            message = f"No graph entity matched {entity_key}={entity_name.strip()!r}."
        elif not evidence:
            message = (
                "The graph entity was found, but no source-backed relationships were returned."
            )
        elif truncated or missing_provenance:
            reasons: list[str] = []
            if truncated:
                reasons.append("one or more relationship groups reached the result limit")
            if missing_provenance:
                reasons.append(
                    f"{missing_provenance} result item(s) lacked sufficient source provenance"
                )
            message = "Partial graph result: " + "; ".join(reasons) + "."
        else:
            message = None

        status = ToolStatus.PARTIAL if is_partial else ToolStatus.SUCCEEDED
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=status,
            data={
                "operation": operation,
                "entity_name": resolved_name,
                "entity_found": entity_found,
                "groups": groups,
                "graph_facts": facts,
                "truncated": truncated,
                "missing_provenance_count": missing_provenance,
                "database": self._config.database,
            },
            evidence=tuple(evidence),
            message=message,
        )

    def _make_evidence_and_fact(
        self,
        *,
        operation: str,
        group_name: str,
        item: dict[str, Any],
        contract: Mapping[str, str],
        entity_name: str,
        seen_evidence: set[str],
    ) -> tuple[EvidenceReference | None, dict[str, Any] | None]:
        """Convert one returned edge/record mapping to evidence and a neutral graph finding."""
        relationship_type = contract["relationship_type"]
        source_record_id = item.get("source_record_id") or item.get("record_id")
        snapshot_id = item.get("snapshot_id")
        if not isinstance(source_record_id, str) or not source_record_id.strip():
            return None, None
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            return None, None
        source_record_id = source_record_id.strip()
        snapshot_id = snapshot_id.strip()

        subject_kind = contract["subject_kind"]
        object_kind = contract["object_kind"]
        if subject_kind == "host_star":
            subject = item.get("name") or entity_name
        elif subject_kind == "catalogue_record":
            subject = source_record_id
        else:
            subject = entity_name

        if object_kind == "planet":
            object_name = item.get("planet_name") or entity_name
        elif object_kind == "discovery_method":
            object_name = item.get("name")
        elif object_kind == "discovery_facility":
            object_name = item.get("name")
        elif object_kind == "publication_reference":
            object_name = item.get("display_name") or item.get("reference_id")
        else:
            object_name = None
        if not isinstance(subject, str) or not subject.strip():
            return None, None
        if not isinstance(object_name, str) or not object_name.strip():
            return None, None
        subject = subject.strip()
        object_name = object_name.strip()

        provenance_key = f"{relationship_type}|{snapshot_id}|{source_record_id}"
        digest = hashlib.sha256(provenance_key.encode("utf-8")).hexdigest()[:16]
        evidence_id = f"graph:{operation}:{digest}"
        if evidence_id in seen_evidence:
            return None, None
        seen_evidence.add(evidence_id)

        details = {
            "relationship_type": relationship_type,
            "subject_kind": subject_kind,
            "subject": subject,
            "object_kind": object_kind,
            "object": object_name,
            "snapshot_id": snapshot_id,
            "source_record_id": source_record_id,
            "source_file": item.get("source_file"),
            "source_row_number": item.get("source_row_number"),
            "relationship_properties": dict(item),
        }
        excerpt = json.dumps(details, ensure_ascii=False, sort_keys=True, allow_nan=False)
        metadata = {
            "operation": operation,
            "group": group_name,
            "relationship_type": relationship_type,
            "subject_kind": subject_kind,
            "object_kind": object_kind,
            "source_record_id": source_record_id,
            "source_file": item.get("source_file"),
            "source_row_number": item.get("source_row_number"),
            "database": self._config.database,
        }
        source_uri = self._http_uri(item.get("href"))
        title = f"Graph relationship: {subject} -[{relationship_type}]-> {object_name}"
        evidence_ref = EvidenceReference(
            evidence_id=evidence_id,
            source_id=f"neo4j:{relationship_type}:{snapshot_id}:{source_record_id}",
            title=title,
            excerpt=excerpt,
            source_uri=source_uri,
            source_kind="neo4j_graph_relationship",
            snapshot_id=snapshot_id,
            record_id=source_record_id,
            metadata=metadata,
        )
        statement = (
            f"The graph records a {relationship_type} relationship from "
            f"{subject_kind.replace('_', ' ')} '{subject}' to "
            f"{object_kind.replace('_', ' ')} '{object_name}'."
        )
        fact = {
            "finding_type": "graph_relationship",
            "statement": statement,
            "evidence_id": evidence_id,
            "data": details,
        }
        return evidence_ref, fact

    @staticmethod
    def _http_uri(value: Any) -> str | None:
        """Retain a publication href only when it is an absolute HTTP(S) URL."""
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = value.strip()
        parsed = urlparse(candidate)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            return None
        return candidate

    def _failure(self, request: ToolRequest, code: str, message: str) -> ToolResult:
        """Return a structured tool failure without executing any graph query."""
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.FAILED,
            data={},
            message=message,
            error_code=code,
        )
