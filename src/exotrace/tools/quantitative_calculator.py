"""Deterministic, provenance-aware calculations over source-verified numeric values.

The tool contains generic mathematical operations only. It does not know exoplanet field
names, scientific facts, question-routing rules, or unit-conversion tables. Its operation
registry is extensible so applications can register additional audited functions.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from exotrace.contracts import EvidenceReference
from exotrace.tools.contracts import ToolDescriptor, ToolRequest, ToolResult, ToolStatus


DecimalEvaluator = Callable[[tuple[Decimal, ...], tuple[str, ...]], tuple[Decimal, str]]


@dataclass(frozen=True, slots=True)
class CalculationOperation:
    """One named, deterministic calculation supported by the calculator registry."""

    operation_id: str
    description: str
    min_operands: int
    max_operands: int | None
    evaluator: DecimalEvaluator

    def __post_init__(self) -> None:
        """Validate the calculation operation metadata."""
        if not self.operation_id or not self.operation_id.strip():
            raise ValueError("operation_id must be a non-empty string.")
        if not self.description or not self.description.strip():
            raise ValueError("description must be a non-empty string.")
        if isinstance(self.min_operands, bool) or not isinstance(self.min_operands, int):
            raise TypeError("min_operands must be an integer.")
        if self.min_operands < 1:
            raise ValueError("min_operands must be positive.")
        if self.max_operands is not None:
            if isinstance(self.max_operands, bool) or not isinstance(self.max_operands, int):
                raise TypeError("max_operands must be an integer or None.")
            if self.max_operands < self.min_operands:
                raise ValueError("max_operands cannot be less than min_operands.")
        if not callable(self.evaluator):
            raise TypeError("evaluator must be callable.")

    def to_dict(self) -> dict[str, Any]:
        """Expose safe planner metadata without executable function objects."""
        return {
            "operation_id": self.operation_id,
            "description": self.description,
            "min_operands": self.min_operands,
            "max_operands": self.max_operands,
        }


class CalculationOperationRegistry:
    """Registry of calculation functions, extensible without changing the agent."""

    def __init__(self, operations: Sequence[CalculationOperation] = ()) -> None:
        """Create a registry and reject duplicate operation identifiers."""
        self._operations: dict[str, CalculationOperation] = {}
        for operation in operations:
            self.register(operation)

    def register(self, operation: CalculationOperation) -> None:
        """Register an operation implementation under a unique stable identifier."""
        if not isinstance(operation, CalculationOperation):
            raise TypeError("operation must be a CalculationOperation.")
        if operation.operation_id in self._operations:
            raise ValueError(f"Calculation operation already registered: {operation.operation_id!r}.")
        self._operations[operation.operation_id] = operation

    def get(self, operation_id: str) -> CalculationOperation:
        """Return an operation by exact identifier."""
        try:
            return self._operations[operation_id]
        except KeyError as exc:
            raise ValueError(f"Unsupported calculation operation: {operation_id!r}.") from exc

    @property
    def operation_ids(self) -> tuple[str, ...]:
        """Return registered operation IDs in registration order."""
        return tuple(self._operations)

    def descriptors(self) -> tuple[dict[str, Any], ...]:
        """Return registry metadata for audit, configuration, and planner schemas."""
        return tuple(operation.to_dict() for operation in self._operations.values())


def _require_matching_units(units: tuple[str, ...], *, operation_id: str) -> str:
    """Require exact unit-label equality; this layer never converts units."""
    if not units:
        raise ValueError(f"{operation_id} requires operands.")
    if any(unit != units[0] for unit in units[1:]):
        raise ValueError(
            f"{operation_id} requires identical unit labels; received {list(units)!r}. "
            "Unit conversion is not performed by this tool."
        )
    return units[0]


def _sum(values: tuple[Decimal, ...], units: tuple[str, ...]) -> tuple[Decimal, str]:
    unit = _require_matching_units(units, operation_id="sum")
    return sum(values, Decimal(0)), unit


def _difference(values: tuple[Decimal, ...], units: tuple[str, ...]) -> tuple[Decimal, str]:
    unit = _require_matching_units(units, operation_id="difference")
    if len(values) != 2:
        raise ValueError("difference requires exactly two operands: minuend, then subtrahend.")
    return values[0] - values[1], unit


def _mean(values: tuple[Decimal, ...], units: tuple[str, ...]) -> tuple[Decimal, str]:
    unit = _require_matching_units(units, operation_id="mean")
    return sum(values, Decimal(0)) / Decimal(len(values)), unit


def _ratio(values: tuple[Decimal, ...], units: tuple[str, ...]) -> tuple[Decimal, str]:
    if len(values) != 2:
        raise ValueError("ratio requires exactly two operands: numerator, then denominator.")
    if values[1] == 0:
        raise ValueError("ratio denominator cannot be zero.")
    numerator_unit, denominator_unit = units
    if numerator_unit == denominator_unit:
        result_unit = "1"
    elif denominator_unit == "1":
        result_unit = numerator_unit
    elif numerator_unit == "1":
        result_unit = f"1/{denominator_unit}"
    else:
        result_unit = f"{numerator_unit}/{denominator_unit}"
    return values[0] / values[1], result_unit


def _percentage_change(
    values: tuple[Decimal, ...], units: tuple[str, ...]
) -> tuple[Decimal, str]:
    _require_matching_units(units, operation_id="percentage_change")
    if len(values) != 2:
        raise ValueError(
            "percentage_change requires two operands: baseline, then comparison value."
        )
    baseline, comparison = values
    if baseline == 0:
        raise ValueError("percentage_change baseline cannot be zero.")
    return ((comparison - baseline) / baseline) * Decimal(100), "%"


def _product(values: tuple[Decimal, ...], units: tuple[str, ...]) -> tuple[Decimal, str]:
    result = Decimal(1)
    for value in values:
        result *= value
    unit_factors = [unit for unit in units if unit != "1"]
    return result, ("*".join(unit_factors) if unit_factors else "1")


def create_default_operation_registry() -> CalculationOperationRegistry:
    """Create the initial generic arithmetic operation set.

    These are stable mathematical primitives, not scientific definitions or query-routing
    rules. Callers can inject another registry or register additional operations explicitly.
    """
    return CalculationOperationRegistry(
        (
            CalculationOperation("sum", "Add two or more compatible values.", 2, None, _sum),
            CalculationOperation(
                "difference", "Subtract the second value from the first.", 2, 2, _difference
            ),
            CalculationOperation("mean", "Calculate the arithmetic mean.", 2, None, _mean),
            CalculationOperation("ratio", "Divide the first value by the second.", 2, 2, _ratio),
            CalculationOperation(
                "percentage_change",
                "Calculate (comparison - baseline) / baseline * 100.",
                2,
                2,
                _percentage_change,
            ),
            CalculationOperation("product", "Multiply two or more values.", 2, None, _product),
        )
    )


class QuantitativeCalculatorTool:
    """Execute deterministic arithmetic only on values matching cited source records."""

    TOOL_ID = "quantitative.calculate"

    def __init__(
        self,
        *,
        operation_registry: CalculationOperationRegistry | None = None,
    ) -> None:
        """Inject an extensible operation registry or use the generic default operations."""
        self._operations = operation_registry or create_default_operation_registry()
        if not self._operations.operation_ids:
            raise ValueError("The calculation operation registry cannot be empty.")

    @property
    def operation_registry(self) -> CalculationOperationRegistry:
        """Return the operation registry used by this tool."""
        return self._operations

    @property
    def descriptor(self) -> ToolDescriptor:
        """Describe the calculator with a schema derived from registered operations."""
        operand_schema = {
            "type": "object",
            "properties": {
                # Source values from catalogue CSV records are preserved as decimal strings
                # to avoid introducing binary-float rounding before Decimal validation.
                "value": {"type": ["number", "string"]},
                "unit": {"type": "string", "minLength": 1},
                "evidence_id": {"type": "string", "minLength": 1},
                "field": {"type": "string", "minLength": 1},
            },
            "required": ["value", "unit", "evidence_id", "field"],
            "additionalProperties": False,
        }
        calculation_schema = {
            "type": "object",
            "properties": {
                "calculation_id": {"type": "string", "minLength": 1},
                "operation": {"type": "string", "enum": list(self._operations.operation_ids)},
                "operands": {
                    "type": "array",
                    "minItems": 1,
                    "items": operand_schema,
                },
            },
            "required": ["calculation_id", "operation", "operands"],
            "additionalProperties": False,
        }
        evidence_schema = {
            "type": "object",
            "properties": {
                "evidence_id": {"type": "string"},
                "source_id": {"type": "string"},
                "title": {"type": "string"},
                "excerpt": {"type": "string"},
                "source_uri": {"type": ["string", "null"]},
                "source_kind": {"type": ["string", "null"]},
                "snapshot_id": {"type": ["string", "null"]},
                "record_id": {"type": ["string", "null"]},
                "metadata": {"type": "object"},
            },
            "required": [
                "evidence_id",
                "source_id",
                "title",
                "excerpt",
                "source_uri",
                "source_kind",
                "snapshot_id",
                "record_id",
                "metadata",
            ],
            "additionalProperties": False,
        }
        return ToolDescriptor(
            tool_id=self.TOOL_ID,
            name="Quantitative Calculator",
            purpose=(
                "Perform registered deterministic calculations on numeric inputs, verifying "
                "that each input value matches the cited structured source record."
            ),
            capabilities=("quantitative.calculate", "quantitative.deterministic"),
            input_schema={
                "type": "object",
                "properties": {
                    "calculations": {
                        "type": "array",
                        "minItems": 1,
                        "items": calculation_schema,
                    },
                    "input_evidence": {
                        "type": "array",
                        "minItems": 1,
                        "items": evidence_schema,
                    },
                },
                "required": ["calculations", "input_evidence"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "calculations": {"type": "array", "items": {"type": "object"}},
                    "input_evidence_count": {"type": "integer"},
                },
            },
            read_only=True,
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        """Validate source values and execute every requested calculation atomically."""
        if request.tool_id != self.TOOL_ID:
            return self._failure(request, "wrong_tool_id", "Request tool ID does not match.")
        arguments = dict(request.arguments)
        if set(arguments) != {"calculations", "input_evidence"}:
            return self._failure(
                request,
                "unsupported_arguments",
                "Arguments must contain exactly calculations and input_evidence.",
            )
        try:
            calculations = self._validate_calculations(arguments["calculations"])
            evidence = self._validate_evidence(arguments["input_evidence"])
            evidence_by_id = {item.evidence_id: item for item in evidence}
            computed: list[dict[str, Any]] = []
            derived_evidence: list[EvidenceReference] = []
            seen_calculation_ids: set[str] = set()
            for calculation in calculations:
                calculation_id = calculation["calculation_id"]
                if calculation_id in seen_calculation_ids:
                    raise ValueError(f"Duplicate calculation_id: {calculation_id!r}.")
                seen_calculation_ids.add(calculation_id)
                operation = self._operations.get(calculation["operation"])
                operands = calculation["operands"]
                if len(operands) < operation.min_operands:
                    raise ValueError(
                        f"Operation {operation.operation_id!r} requires at least "
                        f"{operation.min_operands} operand(s)."
                    )
                if operation.max_operands is not None and len(operands) > operation.max_operands:
                    raise ValueError(
                        f"Operation {operation.operation_id!r} accepts at most "
                        f"{operation.max_operands} operand(s)."
                    )

                source_refs: list[EvidenceReference] = []
                numeric_values: list[Decimal] = []
                units: list[str] = []
                fields: list[str] = []
                for operand_index, operand in enumerate(operands, start=1):
                    source_ref = evidence_by_id.get(operand["evidence_id"])
                    if source_ref is None:
                        raise ValueError(
                            f"Calculation {calculation_id!r} operand {operand_index} cites "
                            f"unknown evidence ID {operand['evidence_id']!r}."
                        )
                    numeric_value = self._parse_decimal(operand["value"], "operand.value")
                    field_name = operand["field"]
                    source_value = self._source_field_value(source_ref, field_name)
                    source_decimal = self._parse_source_decimal(source_value, field_name)
                    if numeric_value != source_decimal:
                        raise ValueError(
                            f"Calculation {calculation_id!r} operand value {numeric_value} does "
                            f"not match field {field_name!r} in evidence {source_ref.evidence_id!r} "
                            f"({source_decimal})."
                        )
                    unit = operand["unit"]
                    if not isinstance(unit, str) or not unit.strip():
                        raise ValueError("Every operand must have a non-empty declared unit label.")
                    source_refs.append(source_ref)
                    numeric_values.append(numeric_value)
                    units.append(unit.strip())
                    fields.append(field_name)

                result_decimal, result_unit = operation.evaluator(
                    tuple(numeric_values), tuple(units)
                )
                if not isinstance(result_decimal, Decimal):
                    raise ValueError(
                        f"Operation {operation.operation_id!r} must return a Decimal result."
                    )
                if not isinstance(result_unit, str) or not result_unit.strip():
                    raise ValueError(
                        f"Operation {operation.operation_id!r} must return a non-empty unit label."
                    )
                result_unit = result_unit.strip()
                if not result_decimal.is_finite():
                    raise ValueError("Calculation produced a non-finite result.")
                result_float = float(result_decimal)
                if not math.isfinite(result_float):
                    raise ValueError("Calculation result cannot be represented as a finite JSON number.")
                if result_decimal != 0 and result_float == 0.0:
                    raise ValueError("Calculation result underflows the JSON numeric representation.")

                distinct_snapshots = {
                    item.snapshot_id for item in source_refs if item.snapshot_id is not None
                }
                output_snapshot = (
                    next(iter(distinct_snapshots)) if len(distinct_snapshots) == 1 else None
                )
                input_ids = [item.evidence_id for item in source_refs]
                source_ids = [item.source_id for item in source_refs]
                data_item = {
                    "calculation_id": calculation_id,
                    "operation": operation.operation_id,
                    "operation_description": operation.description,
                    "value": result_float,
                    "value_exact": format(result_decimal, "f"),
                    "unit": result_unit,
                    "input_evidence_ids": input_ids,
                    "input_source_ids": source_ids,
                    "input_fields": fields,
                    "input_units": units,
                }
                computed.append(data_item)
                derived_payload = {
                    "calculation_id": calculation_id,
                    "operation": operation.operation_id,
                    "value": result_float,
                    "value_exact": format(result_decimal, "f"),
                    "unit": result_unit,
                    "input_evidence_ids": input_ids,
                    "input_source_ids": source_ids,
                    "input_fields": fields,
                    "input_units": units,
                }
                derived_evidence.append(
                    EvidenceReference(
                        evidence_id=f"calculation:{request.call_id}:{calculation_id}",
                        source_id=f"derived-calculation:{request.call_id}:{calculation_id}",
                        title=f"Derived calculation: {calculation_id}",
                        excerpt=json.dumps(
                            derived_payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            allow_nan=False,
                        ),
                        source_uri=None,
                        source_kind="exotrace_derived_calculation",
                        snapshot_id=output_snapshot,
                        record_id=None,
                        metadata={
                            **derived_payload,
                            "operation_description": operation.description,
                            "unit_labels_independently_verified": False,
                            "unit_conversion_performed": False,
                            "input_source_uris": [item.source_uri for item in source_refs],
                        },
                    )
                )
            return ToolResult(
                call_id=request.call_id,
                tool_id=request.tool_id,
                status=ToolStatus.SUCCEEDED,
                data={
                    "calculations": computed,
                    "input_evidence_count": len(evidence),
                    "operation_registry": list(self._operations.operation_ids),
                },
                evidence=tuple(derived_evidence),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError) as exc:
            return self._failure(request, "invalid_calculation_request", str(exc))

    def _validate_calculations(self, raw_calculations: Any) -> list[dict[str, Any]]:
        """Check the generic calculation request structure before execution."""
        if not isinstance(raw_calculations, list) or not raw_calculations:
            raise ValueError("calculations must be a non-empty array.")
        normalized: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_calculations, start=1):
            if not isinstance(raw, Mapping):
                raise ValueError(f"calculations[{index - 1}] must be an object.")
            if set(raw) != {"calculation_id", "operation", "operands"}:
                raise ValueError(
                    f"calculations[{index - 1}] must contain calculation_id, operation, and operands."
                )
            calculation_id = raw["calculation_id"]
            operation_id = raw["operation"]
            if not isinstance(calculation_id, str) or not calculation_id.strip():
                raise ValueError(f"calculations[{index - 1}].calculation_id must be non-empty.")
            if not isinstance(operation_id, str) or not operation_id.strip():
                raise ValueError(f"calculations[{index - 1}].operation must be non-empty.")
            self._operations.get(operation_id)
            raw_operands = raw["operands"]
            if not isinstance(raw_operands, list) or not raw_operands:
                raise ValueError(f"calculations[{index - 1}].operands must be a non-empty array.")
            operands: list[dict[str, Any]] = []
            for operand_index, raw_operand in enumerate(raw_operands, start=1):
                if not isinstance(raw_operand, Mapping):
                    raise ValueError(
                        f"calculations[{index - 1}].operands[{operand_index - 1}] must be an object."
                    )
                if set(raw_operand) != {"value", "unit", "evidence_id", "field"}:
                    raise ValueError(
                        "Each operand must contain exactly value, unit, evidence_id, and field."
                    )
                value = raw_operand["value"]
                if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                    raise ValueError("operand.value must be a JSON number or decimal string.")
                numeric_value = self._parse_decimal(value, "operand.value")
                unit = raw_operand["unit"]
                evidence_id = raw_operand["evidence_id"]
                field_name = raw_operand["field"]
                for field_value, field_label in (
                    (unit, "unit"),
                    (evidence_id, "evidence_id"),
                    (field_name, "field"),
                ):
                    if not isinstance(field_value, str) or not field_value.strip():
                        raise ValueError(f"operand.{field_label} must be a non-empty string.")
                operands.append(
                    {
                        "value": value,
                        "unit": unit.strip(),
                        "evidence_id": evidence_id.strip(),
                        "field": field_name.strip(),
                    }
                )
            normalized.append(
                {
                    "calculation_id": calculation_id.strip(),
                    "operation": operation_id,
                    "operands": operands,
                }
            )
        return normalized

    @staticmethod
    def _validate_evidence(raw_evidence: Any) -> tuple[EvidenceReference, ...]:
        """Restore strongly validated evidence objects from the requesting agent payload."""
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise ValueError("input_evidence must be a non-empty array.")
        evidence: list[EvidenceReference] = []
        for index, raw in enumerate(raw_evidence, start=1):
            if not isinstance(raw, Mapping):
                raise ValueError(f"input_evidence[{index - 1}] must be an object.")
            try:
                item = EvidenceReference(
                    evidence_id=raw["evidence_id"],
                    source_id=raw["source_id"],
                    title=raw["title"],
                    excerpt=raw["excerpt"],
                    source_uri=raw.get("source_uri"),
                    source_kind=raw.get("source_kind"),
                    snapshot_id=raw.get("snapshot_id"),
                    record_id=raw.get("record_id"),
                    metadata=raw.get("metadata", {}),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Malformed input evidence item {index}: {exc}") from exc
            evidence.append(item)
        evidence_ids = [item.evidence_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("input_evidence cannot contain duplicate evidence IDs.")
        return tuple(evidence)

    @staticmethod
    def _source_field_value(evidence: EvidenceReference, field_name: str) -> Any:
        """Return a value only when the cited evidence is a structured source-record excerpt."""
        try:
            parsed = json.loads(evidence.excerpt)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Evidence {evidence.evidence_id!r} does not contain a structured JSON record."
            ) from exc
        if not isinstance(parsed, Mapping):
            raise ValueError(f"Evidence {evidence.evidence_id!r} is not a JSON record object.")
        selected_fields = evidence.metadata.get("selected_fields")
        if isinstance(selected_fields, list) and field_name not in selected_fields:
            raise ValueError(
                f"Field {field_name!r} was not selected into evidence {evidence.evidence_id!r}."
            )
        if field_name not in parsed:
            raise ValueError(
                f"Field {field_name!r} is not present in evidence {evidence.evidence_id!r}."
            )
        value = parsed[field_name]
        if value is None or isinstance(value, bool):
            raise ValueError(
                f"Field {field_name!r} in evidence {evidence.evidence_id!r} is not numeric."
            )
        return value

    @staticmethod
    def _parse_source_decimal(value: Any, field_name: str) -> Decimal:
        """Parse a finite source-record numeric value without guessing missing values."""
        if not isinstance(value, (str, int, float)):
            raise ValueError(f"Source field {field_name!r} is not a numeric scalar.")
        try:
            parsed = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(f"Source field {field_name!r} is not numeric: {value!r}.") from exc
        if not parsed.is_finite():
            raise ValueError(f"Source field {field_name!r} is not finite.")
        return parsed

    @staticmethod
    def _parse_decimal(value: Any, field_name: str) -> Decimal:
        """Parse a finite JSON number or exact decimal string into Decimal."""
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(f"{field_name} must be a JSON number or decimal string.")
        try:
            parsed = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} is not numeric.") from exc
        if not parsed.is_finite():
            raise ValueError(f"{field_name} must be finite.")
        return parsed

    @staticmethod
    def _failure(request: ToolRequest, code: str, message: str) -> ToolResult:
        """Return a structured failure with no derived result evidence."""
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.FAILED,
            message=message,
            error_code=code,
        )
