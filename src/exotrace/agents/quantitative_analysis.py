"""Bounded Quantitative Analysis Agent for deterministic, source-verified calculations."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from exotrace.agents._support import validate_specialist_task
from exotrace.agents.contracts import (
    AgentDescriptor,
    AgentResult,
    AgentStatus,
    AgentTask,
    SpecialistAgent,
)
from exotrace.contracts import EvidenceReference, Finding
from exotrace.tools.contracts import ToolExecutor, ToolRequest, ToolStatus
from exotrace.tools.quantitative_calculator import QuantitativeCalculatorTool


class QuantitativeAnalysisAgent:
    """Calculate results from values delivered by explicitly declared dependency tasks.

    The planner supplies source task keys and source field names, not numeric measurements.
    The orchestrator hands this agent only evidence returned by declared dependencies. This
    agent resolves each operand from those structured records and asks the calculator tool to
    independently verify every numeric value against the same evidence.

    Catalogue unit metadata is not available as a normalized field in all current source rows.
    For raw catalogue fields, the agent therefore derives an opaque source-native unit token
    from the field, snapshot, and source kind. It does not claim this token is a physical unit.
    Derived calculations reuse the unit label recorded by the calculator that produced them.
    """

    AGENT_ID = "quantitative_analysis"
    CAPABILITY_ID = "quantitative.calculate"
    PRODUCER_TASK_KEY_METADATA = "exotrace_producer_task_key"

    def __init__(self, calculator_tool: QuantitativeCalculatorTool | None = None) -> None:
        """Bind the task contract to the calculator's live operation registry."""
        self._calculator_tool = calculator_tool or QuantitativeCalculatorTool()
        self._tool_id = self._calculator_tool.descriptor.tool_id

    @property
    def descriptor(self) -> AgentDescriptor:
        """Declare an input schema derived from the calculator's registered operations."""
        operand_schema = {
            "type": "object",
            "properties": {
                "source_task_key": {"type": "string", "minLength": 1},
                "field": {"type": "string", "minLength": 1},
            },
            "required": ["source_task_key", "field"],
            "additionalProperties": False,
        }
        calculation_schema = {
            "type": "object",
            "properties": {
                "calculation_id": {"type": "string", "minLength": 1},
                "operation": {
                    "type": "string",
                    "enum": list(self._calculator_tool.operation_registry.operation_ids),
                },
                "operands": {
                    "type": "array",
                    "minItems": 1,
                    "items": operand_schema,
                },
            },
            "required": ["calculation_id", "operation", "operands"],
            "additionalProperties": False,
        }
        return AgentDescriptor(
            agent_id=self.AGENT_ID,
            name="Quantitative Analysis Agent",
            responsibility=(
                "Perform deterministic calculations using numeric values resolved from "
                "structured source evidence produced by explicitly declared prerequisite tasks. "
                "Reference operands by upstream task key and source field; do not supply or "
                "invent the numeric values. Preserve field and source provenance. Do not retrieve "
                "data, infer physical units, convert units, or interpret scientific meaning."
            ),
            capabilities=(self.CAPABILITY_ID, "quantitative.deterministic", "source.provenance"),
            allowed_tool_ids=(self._tool_id,),
            task_context_schema={
                "type": "object",
                "properties": {
                    "calculations": {
                        "type": "array",
                        "minItems": 1,
                        "items": calculation_schema,
                    }
                },
                "required": ["calculations"],
                "additionalProperties": False,
            },
        )

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        """Resolve dependency evidence, calculate deterministically, and preserve provenance."""
        descriptor = self.descriptor
        preflight = validate_specialist_task(
            task,
            descriptor,
            required_tool_id=self._tool_id,
        )
        if preflight is not None:
            return preflight

        raw_calculations = task.context.get("calculations")
        if not isinstance(raw_calculations, list) or not raw_calculations:
            return self._failure_result(
                task,
                descriptor,
                code="missing_calculations",
                message="context.calculations must be a non-empty array.",
                summary="The quantitative task has no structured calculations.",
                gaps=("Provide at least one calculation in context.calculations.",),
            )
        if not task.input_evidence:
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.INSUFFICIENT_EVIDENCE,
                summary="No prerequisite task supplied source evidence for the calculation.",
                gaps=(
                    "Declare dependencies on tasks that return the required structured source "
                    "records. The quantitative agent will not trust numeric values supplied by "
                    "the planner alone.",
                ),
                metadata={"calculations_requested": len(raw_calculations)},
            )

        try:
            resolved_calculations = self._resolve_calculations(
                raw_calculations,
                task.input_evidence,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self._failure_result(
                task,
                descriptor,
                code="calculation_operand_resolution_failed",
                message=str(exc),
                summary="The quantitative agent could not resolve every operand to unique source evidence.",
                gaps=(str(exc),),
                evidence=task.input_evidence,
                metadata={"calculations_requested": len(raw_calculations)},
            )

        tool_result = tools.execute(
            ToolRequest(
                call_id=f"{task.task_id}:{self._tool_id}",
                tool_id=self._tool_id,
                arguments={
                    "calculations": resolved_calculations,
                    "input_evidence": [item.to_dict() for item in task.input_evidence],
                },
            )
        )
        if tool_result.status is ToolStatus.FAILED:
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="The quantitative calculation could not be completed safely.",
                evidence=task.input_evidence,
                gaps=(tool_result.message or "Calculator rejected the request.",),
                tool_ids_used=(self._tool_id,),
                error_code=tool_result.error_code or "calculation_failed",
                error_message=tool_result.message or "Calculator rejected the request.",
                metadata={"tool_result": tool_result.to_dict()},
            )

        result_items = tool_result.data.get("calculations")
        if not isinstance(result_items, list) or len(result_items) != len(tool_result.evidence):
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="The calculator returned an inconsistent result shape.",
                evidence=task.input_evidence,
                tool_ids_used=(self._tool_id,),
                error_code="invalid_calculator_result",
                error_message="Each calculation must have exactly one derived evidence item.",
                metadata={"tool_result": tool_result.to_dict()},
            )

        findings = tuple(
            Finding(
                finding_id=f"{task.task_id}:{item['calculation_id']}",
                statement=(f"{item['calculation_id']} = {item['value_exact']} {item['unit']}").rstrip(),
                finding_type="derived_quantitative_result",
                evidence_ids=(derived.evidence_id,),
                data={
                    "calculation_id": item["calculation_id"],
                    "operation": item["operation"],
                    "value": item["value"],
                    "value_exact": item["value_exact"],
                    "unit": item["unit"],
                    "input_evidence_ids": item["input_evidence_ids"],
                    "input_source_ids": item["input_source_ids"],
                    "input_fields": item["input_fields"],
                    "input_units": item["input_units"],
                },
            )
            for item, derived in zip(result_items, tool_result.evidence, strict=True)
        )
        result = AgentResult(
            task_id=task.task_id,
            agent_id=descriptor.agent_id,
            status=AgentStatus.SUCCEEDED,
            summary=f"Completed {len(findings)} deterministic calculation(s).",
            findings=findings,
            evidence=(*task.input_evidence, *tool_result.evidence),
            tool_ids_used=(self._tool_id,),
            metadata={
                "calculations": result_items,
                "operation_registry": tool_result.data.get("operation_registry", []),
                "physical_unit_labels_resolved": False,
                "unit_conversion_performed": False,
            },
        )
        result.validate_for(task, descriptor)
        return result

    def _resolve_calculations(
        self,
        raw_calculations: list[Any],
        evidence: tuple[EvidenceReference, ...],
    ) -> list[dict[str, Any]]:
        """Resolve symbolic source-task references into exact values and evidence IDs."""
        resolved: list[dict[str, Any]] = []
        seen_calculation_ids: set[str] = set()
        for calculation_index, raw_calculation in enumerate(raw_calculations, start=1):
            if not isinstance(raw_calculation, Mapping):
                raise ValueError(f"calculations[{calculation_index - 1}] must be an object.")
            calculation_id = raw_calculation.get("calculation_id")
            operation = raw_calculation.get("operation")
            raw_operands = raw_calculation.get("operands")
            if not isinstance(calculation_id, str) or not calculation_id.strip():
                raise ValueError(f"calculations[{calculation_index - 1}].calculation_id is required.")
            if calculation_id in seen_calculation_ids:
                raise ValueError(f"Duplicate calculation_id: {calculation_id!r}.")
            seen_calculation_ids.add(calculation_id)
            if not isinstance(operation, str) or not operation.strip():
                raise ValueError(f"calculations[{calculation_index - 1}].operation is required.")
            if not isinstance(raw_operands, list) or not raw_operands:
                raise ValueError(f"calculations[{calculation_index - 1}].operands must be non-empty.")

            operands: list[dict[str, Any]] = []
            for operand_index, raw_operand in enumerate(raw_operands, start=1):
                if not isinstance(raw_operand, Mapping):
                    raise ValueError(
                        f"Calculation {calculation_id!r} operand {operand_index} must be an object."
                    )
                if set(raw_operand) != {"source_task_key", "field"}:
                    raise ValueError(
                        f"Calculation {calculation_id!r} operand {operand_index} must contain "
                        "exactly source_task_key and field."
                    )
                source_task_key = raw_operand["source_task_key"]
                field_name = raw_operand["field"]
                if not isinstance(source_task_key, str) or not source_task_key.strip():
                    raise ValueError("operand.source_task_key must be a non-empty task key.")
                if not isinstance(field_name, str) or not field_name.strip():
                    raise ValueError("operand.field must be a non-empty source field name.")
                source_evidence, source_value, unit = self._resolve_operand_source(
                    evidence,
                    source_task_key=source_task_key,
                    field_name=field_name,
                )
                operands.append(
                    {
                        # Preserve the original textual decimal representation; the calculator
                        # parses it with Decimal and independently compares it to the source.
                        "value": source_value,
                        "unit": unit,
                        "evidence_id": source_evidence.evidence_id,
                        "field": field_name,
                    }
                )
            resolved.append(
                {
                    "calculation_id": calculation_id.strip(),
                    "operation": operation,
                    "operands": operands,
                }
            )
        return resolved

    @classmethod
    def _resolve_operand_source(
        cls,
        evidence: tuple[EvidenceReference, ...],
        *,
        source_task_key: str,
        field_name: str,
    ) -> tuple[EvidenceReference, str | int | float, str]:
        """Find exactly one structured field value emitted by the requested upstream task."""
        candidates: list[tuple[EvidenceReference, Mapping[str, Any], Any]] = []
        for item in evidence:
            if item.metadata.get(cls.PRODUCER_TASK_KEY_METADATA) != source_task_key:
                continue
            try:
                parsed = json.loads(item.excerpt)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, Mapping) or field_name not in parsed:
                continue
            selected_fields = item.metadata.get("selected_fields")
            if isinstance(selected_fields, list) and field_name not in selected_fields:
                continue
            value = parsed[field_name]
            if value is None or isinstance(value, bool):
                continue
            try:
                numeric = Decimal(str(value).strip())
            except (InvalidOperation, AttributeError):
                continue
            if not numeric.is_finite():
                continue
            if isinstance(value, (str, int, float)):
                candidates.append((item, parsed, value))

        if not candidates:
            raise ValueError(
                f"No numeric source field {field_name!r} was found in evidence produced by "
                f"dependency task {source_task_key!r}. Confirm the dependency and request this "
                "field from the upstream source tool."
            )
        if len(candidates) > 1:
            candidate_ids = [candidate[0].evidence_id for candidate in candidates]
            raise ValueError(
                f"Field {field_name!r} is ambiguous in dependency task {source_task_key!r}; "
                f"matching evidence IDs: {candidate_ids}. Narrow the upstream task to one "
                "source record before calculating."
            )
        source, parsed, value = candidates[0]
        unit = cls._source_unit_label(source, parsed, field_name)
        return source, value, unit

    @staticmethod
    def _source_unit_label(
        evidence: EvidenceReference,
        parsed_record: Mapping[str, Any],
        field_name: str,
    ) -> str:
        """Return a derived unit label without pretending unknown source units are known."""
        if evidence.source_kind == "exotrace_derived_calculation":
            derived_unit = parsed_record.get("unit") or evidence.metadata.get("unit")
            if isinstance(derived_unit, str) and derived_unit.strip():
                return derived_unit.strip()
            raise ValueError(
                f"Derived evidence {evidence.evidence_id!r} does not declare a unit label."
            )
        declared_unit = evidence.metadata.get("declared_unit")
        if isinstance(declared_unit, str) and declared_unit.strip():
            return declared_unit.strip()
        snapshot = evidence.snapshot_id or evidence.source_kind or evidence.source_id
        return f"source-native:{field_name}@{snapshot}"

    @staticmethod
    def _failure_result(
        task: AgentTask,
        descriptor: AgentDescriptor,
        *,
        code: str,
        message: str,
        summary: str,
        gaps: tuple[str, ...],
        evidence: tuple[EvidenceReference, ...] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentResult:
        """Create a consistent failed result without claiming the calculator ran."""
        return AgentResult(
            task_id=task.task_id,
            agent_id=descriptor.agent_id,
            status=AgentStatus.FAILED,
            summary=summary,
            evidence=evidence,
            gaps=gaps,
            error_code=code,
            error_message=message,
            metadata=dict(metadata or {}),
        )
