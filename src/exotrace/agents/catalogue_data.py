"""Specialist that retrieves raw, provenance-preserving catalogue values."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from exotrace.agents._support import validate_specialist_task
from exotrace.agents.contracts import (
    AgentDescriptor,
    AgentResult,
    AgentStatus,
    AgentTask,
    SpecialistAgent,
)
from exotrace.contracts import Finding
from exotrace.tools.catalogue_lookup import CatalogueRecordLookupTool
from exotrace.tools.contracts import ToolExecutor, ToolRequest, ToolStatus


class CatalogueDataAgent:
    """Look up source-record values using explicit structured filters and field names.

    This specialist does not parse natural-language questions into database filters, define
    scientific parameters, calculate derived values, or infer missing measurements. The planner
    supplies a compact list of explicit ``field``/``value`` filter clauses and requested fields.
    For broad profile/property requests, the planner may omit ``fields`` so this agent uses the
    complete field list supplied by the validated live catalogue schema. Legacy direct callers
    may still pass a mapping of column names to filter values.
    """

    AGENT_ID = "catalogue_data"
    TOOL_ID = CatalogueRecordLookupTool.TOOL_ID

    def __init__(self, *, available_fields: Sequence[str] | None = None) -> None:
        """Accept the loaded catalogue's field names as source-derived planning metadata."""
        if available_fields is None:
            self._available_fields: tuple[str, ...] | None = None
        else:
            normalized = tuple(available_fields)
            if any(not isinstance(item, str) or not item.strip() for item in normalized):
                raise ValueError("available_fields must contain non-empty strings.")
            if len(set(normalized)) != len(normalized):
                raise ValueError("available_fields cannot contain duplicates.")
            if not normalized:
                raise ValueError("available_fields cannot be empty when supplied.")
            self._available_fields = normalized

    @property
    def descriptor(self) -> AgentDescriptor:
        """Declare the narrow catalogue-retrieval responsibility and tool permission."""
        filter_item_properties: dict[str, Any] = {
            "field": {
                "type": "string",
                "minLength": 1,
                **(
                    {"enum": list(self._available_fields)}
                    if self._available_fields is not None
                    else {}
                ),
            },
            "value": {"type": "string", "minLength": 1},
        }
        # A list of field/value pairs keeps the structured planner schema compact. A map with
        # every one of the source's ~70 columns forced the model to emit nullable placeholders
        # for all fields; some were returned as the literal string "null" and became real filters.
        filter_schema: dict[str, Any] = {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": filter_item_properties,
                "required": ["field", "value"],
                "additionalProperties": False,
            },
            "uniqueItems": True,
        }

        return AgentDescriptor(
            agent_id=self.AGENT_ID,
            name="Catalogue Data Agent",
            responsibility=(
                "Retrieve raw field values from the validated, frozen NASA PSCompPars "
                "snapshot by structured filters; preserve record identity, source fields, "
                "and snapshot provenance. Do not interpret or calculate measurements."
            ),
            capabilities=(
                "catalogue.lookup",
                "catalogue.raw_values",
                "source.provenance",
            ),
            allowed_tool_ids=(self.TOOL_ID,),
            task_context_schema={
                "type": "object",
                "properties": {
                    "filters": filter_schema,
                    "fields": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            **(
                                {"enum": list(self._available_fields)}
                                if self._available_fields is not None
                                else {}
                            ),
                        },
                        "uniqueItems": True,
                    },
                    "match_mode": {"type": "string", "enum": ["exact", "contains"]},
                    "limit": {"type": "integer", "minimum": 1},
                },
                # Filters remain mandatory. Fields are optional so broad profile requests can
                # use the source-derived default while explicit narrow requests stay explicit.
                "required": ["filters"],
                "additionalProperties": False,
            },
        )

    @staticmethod
    def _normalize_filters(raw_filters: Any) -> dict[str, str]:
        """Normalize filter pairs to the lookup tool's mapping contract.

        The planner-facing contract uses a compact array of ``{"field", "value"}`` objects.
        Mapping input remains supported for direct callers and existing unit tests.
        """
        if isinstance(raw_filters, Mapping):
            filters = dict(raw_filters)
        elif isinstance(raw_filters, list) and raw_filters:
            filters = {}
            for index, condition in enumerate(raw_filters):
                if not isinstance(condition, Mapping):
                    raise ValueError(f"Filter clause {index + 1} must be an object.")
                if set(condition) != {"field", "value"}:
                    raise ValueError(
                        f"Filter clause {index + 1} must contain exactly 'field' and 'value'."
                    )
                field_name = condition.get("field")
                filter_value = condition.get("value")
                if not isinstance(field_name, str) or not field_name.strip():
                    raise ValueError(f"Filter clause {index + 1} has an invalid field name.")
                if not isinstance(filter_value, str) or not filter_value.strip():
                    raise ValueError(f"Filter clause {index + 1} has an invalid filter value.")
                if field_name in filters:
                    raise ValueError(f"Filter field {field_name!r} was supplied more than once.")
                filters[field_name] = filter_value
        else:
            raise ValueError("Provide a non-empty context.filters array of field/value clauses.")

        if not filters:
            raise ValueError("At least one catalogue filter is required.")
        normalized: dict[str, str] = {}
        for field_name, filter_value in filters.items():
            if not isinstance(field_name, str) or not field_name.strip():
                raise ValueError("Catalogue filter field names must be non-empty strings.")
            if not isinstance(filter_value, str) or not filter_value.strip():
                raise ValueError(f"Catalogue filter {field_name!r} has an empty value.")
            if filter_value.strip().casefold() in {"null", "none", "n/a", "<null>"}:
                raise ValueError(
                    f"Catalogue filter {field_name!r} uses the placeholder {filter_value!r}; "
                    "omit a filter when the user did not specify a predicate."
                )
            normalized[field_name] = filter_value.strip()
        return normalized

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        """Execute one explicitly structured record lookup and return raw source values."""
        descriptor = self.descriptor
        preflight = validate_specialist_task(
            task,
            descriptor,
            required_tool_id=self.TOOL_ID,
        )
        if preflight is not None:
            return preflight

        raw_filters = task.context.get("filters")
        fields = task.context.get("fields")
        if fields is None and self._available_fields is not None:
            # Source columns come from the validated catalogue at runtime, not a hardcoded list.
            fields = list(self._available_fields)
        if raw_filters is None or raw_filters == [] or raw_filters == {}:
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="The catalogue task requires structured column filters.",
                gaps=("Provide a non-empty context.filters list of field/value clauses.",),
                error_code="missing_structured_filters",
                error_message=(
                    "CatalogueDataAgent does not infer record filters from natural-language "
                    "question text. Provide context.filters explicitly."
                ),
            )
        try:
            filters = self._normalize_filters(raw_filters)
        except (TypeError, ValueError) as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="The catalogue task contains invalid structured filters.",
                gaps=(str(exc),),
                error_code="invalid_structured_filters",
                error_message=str(exc),
            )
        if not isinstance(fields, list) or not fields:
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="The catalogue task requires an explicit field list.",
                gaps=("Provide the source column names to retrieve in context.fields.",),
                error_code="missing_requested_fields",
                error_message="context.fields must be a non-empty list of catalogue column names.",
            )

        arguments: dict[str, Any] = {"filters": filters, "fields": list(fields)}
        for optional_key in ("match_mode", "limit"):
            if optional_key in task.context:
                arguments[optional_key] = task.context[optional_key]

        tool_result = tools.execute(
            ToolRequest(
                call_id=f"{task.task_id}:{self.TOOL_ID}",
                tool_id=self.TOOL_ID,
                arguments=arguments,
            )
        )
        if tool_result.status is ToolStatus.FAILED:
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="The catalogue lookup failed.",
                evidence=tool_result.evidence,
                tool_ids_used=(self.TOOL_ID,),
                error_code=tool_result.error_code or "catalogue_lookup_failed",
                error_message=tool_result.message or "The catalogue lookup tool failed.",
                metadata={"tool_result": tool_result.to_dict()},
            )

        findings = tuple(
            Finding(
                finding_id=f"{task.task_id}:{item.evidence_id}",
                statement=item.excerpt,
                finding_type="catalogue_record_values",
                evidence_ids=(item.evidence_id,),
                data={
                    "title": item.title,
                    "source_uri": item.source_uri,
                    "source_kind": item.source_kind,
                    "snapshot_id": item.snapshot_id,
                    "record_id": item.record_id,
                    "source_metadata": dict(item.metadata),
                },
            )
            for item in tool_result.evidence
        )

        gaps: tuple[str, ...] = ()
        if not tool_result.evidence:
            status = AgentStatus.INSUFFICIENT_EVIDENCE
            summary = "No catalogue records matched the supplied structured filters."
            gaps = (
                tool_result.message
                or "No catalogue records matched the supplied structured filters.",
            )
        elif tool_result.status is ToolStatus.PARTIAL:
            status = AgentStatus.PARTIAL
            summary = (
                f"Retrieved {len(tool_result.evidence)} catalogue record(s), but the result "
                "set was limited."
            )
            if tool_result.message:
                gaps = (tool_result.message,)
        else:
            status = AgentStatus.SUCCEEDED
            summary = f"Retrieved {len(tool_result.evidence)} catalogue record(s)."

        result = AgentResult(
            task_id=task.task_id,
            agent_id=descriptor.agent_id,
            status=status,
            summary=summary,
            findings=findings,
            evidence=tool_result.evidence,
            gaps=gaps,
            tool_ids_used=(self.TOOL_ID,),
            metadata={"lookup": dict(tool_result.data)},
        )
        result.validate_for(task, descriptor)
        return result
