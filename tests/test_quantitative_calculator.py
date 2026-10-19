"""Tests for deterministic calculations and source-record value validation."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from exotrace.contracts import EvidenceReference
from exotrace.tools.contracts import ToolRequest, ToolStatus
from exotrace.tools.quantitative_calculator import (
    CalculationOperation,
    CalculationOperationRegistry,
    QuantitativeCalculatorTool,
    create_default_operation_registry,
)


def make_evidence(
    evidence_id: str,
    *,
    field: str,
    value: str,
    source_id: str | None = None,
    unit_metadata: str | None = None,
) -> EvidenceReference:
    """Create a source-record evidence fixture with source fields preserved as strings."""
    metadata: dict[str, Any] = {"selected_fields": [field]}
    if unit_metadata:
        metadata["declared_unit"] = unit_metadata
    return EvidenceReference(
        evidence_id=evidence_id,
        source_id=source_id or f"snapshot::record-{evidence_id}",
        title=f"Source record {evidence_id}",
        excerpt=json.dumps({field: value}),
        source_uri="https://example.invalid/source",
        source_kind="test_catalogue_record",
        snapshot_id="snapshot-test",
        record_id=f"snapshot::record-{evidence_id}",
        metadata=metadata,
    )


def operand(value: float, unit: str, evidence_id: str, field: str) -> dict[str, Any]:
    """Build the structured operand contract used by both agent and calculator."""
    return {
        "value": value,
        "unit": unit,
        "evidence_id": evidence_id,
        "field": field,
    }


def call_calculator(
    calculations: list[dict[str, Any]],
    evidence: list[EvidenceReference],
    *,
    tool: QuantitativeCalculatorTool | None = None,
):
    """Invoke the tool with source evidence serialized from typed references."""
    calculator = tool or QuantitativeCalculatorTool()
    return calculator.execute(
        ToolRequest(
            call_id="calculator-test-call",
            tool_id=calculator.TOOL_ID,
            arguments={
                "calculations": calculations,
                "input_evidence": [item.to_dict() for item in evidence],
            },
        )
    )


def test_default_registry_exposes_generic_arithmetic_operations() -> None:
    registry = create_default_operation_registry()

    assert registry.operation_ids == (
        "sum",
        "difference",
        "mean",
        "ratio",
        "percentage_change",
        "product",
    )


def test_calculator_operation_registry_rejects_duplicate_ids() -> None:
    operation = CalculationOperation(
        "increment",
        "Add one to a value.",
        1,
        1,
        lambda values, units: (values[0] + Decimal(1), units[0]),
    )
    registry = CalculationOperationRegistry((operation,))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(operation)


def test_calculator_computes_difference_and_preserves_derived_provenance() -> None:
    evidence = [
        make_evidence("e1", field="measurement", value="12.5"),
        make_evidence("e2", field="measurement", value="7.25"),
    ]
    result = call_calculator(
        [
            {
                "calculation_id": "record-difference",
                "operation": "difference",
                "operands": [
                    operand(12.5, "km", "e1", "measurement"),
                    operand(7.25, "km", "e2", "measurement"),
                ],
            }
        ],
        evidence,
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.data["calculations"][0]["value"] == 5.25
    assert result.data["calculations"][0]["value_exact"] == "5.25"
    assert result.data["calculations"][0]["unit"] == "km"
    assert result.evidence[0].metadata["input_evidence_ids"] == ["e1", "e2"]
    assert result.evidence[0].snapshot_id == "snapshot-test"
    assert result.evidence[0].source_kind == "exotrace_derived_calculation"


def test_calculator_computes_sum_mean_product_and_ratio() -> None:
    evidence = [
        make_evidence("e1", field="measure", value="4"),
        make_evidence("e2", field="measure", value="8"),
    ]
    calculations = [
        {
            "calculation_id": "sum-1",
            "operation": "sum",
            "operands": [operand(4, "kg", "e1", "measure"), operand(8, "kg", "e2", "measure")],
        },
        {
            "calculation_id": "mean-1",
            "operation": "mean",
            "operands": [operand(4, "kg", "e1", "measure"), operand(8, "kg", "e2", "measure")],
        },
        {
            "calculation_id": "product-1",
            "operation": "product",
            "operands": [operand(4, "kg", "e1", "measure"), operand(8, "s", "e2", "measure")],
        },
        {
            "calculation_id": "ratio-1",
            "operation": "ratio",
            "operands": [operand(8, "kg", "e2", "measure"), operand(4, "kg", "e1", "measure")],
        },
    ]

    result = call_calculator(calculations, evidence)

    assert result.status is ToolStatus.SUCCEEDED
    by_id = {item["calculation_id"]: item for item in result.data["calculations"]}
    assert by_id["sum-1"]["value"] == 12.0
    assert by_id["mean-1"]["value"] == 6.0
    assert by_id["product-1"]["value"] == 32.0
    assert by_id["product-1"]["unit"] == "kg*s"
    assert by_id["ratio-1"]["value"] == 2.0
    assert by_id["ratio-1"]["unit"] == "1"


def test_percentage_change_uses_first_operand_as_baseline() -> None:
    evidence = [
        make_evidence("old", field="measurement", value="10"),
        make_evidence("new", field="measurement", value="15"),
    ]
    result = call_calculator(
        [
            {
                "calculation_id": "growth",
                "operation": "percentage_change",
                "operands": [
                    operand(10, "count", "old", "measurement"),
                    operand(15, "count", "new", "measurement"),
                ],
            }
        ],
        evidence,
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.data["calculations"][0]["value"] == 50.0
    assert result.data["calculations"][0]["unit"] == "%"


@pytest.mark.parametrize("operation", ["difference", "sum", "mean", "percentage_change"])
def test_same_unit_operations_reject_incompatible_unit_labels(operation: str) -> None:
    evidence = [
        make_evidence("e1", field="measure", value="10"),
        make_evidence("e2", field="measure", value="4"),
    ]
    operands = [operand(10, "km", "e1", "measure"), operand(4, "m", "e2", "measure")]
    result = call_calculator(
        [{"calculation_id": "mismatch", "operation": operation, "operands": operands}],
        evidence,
    )

    assert result.status is ToolStatus.FAILED
    assert "identical unit labels" in (result.message or "")


def test_ratio_rejects_zero_denominator() -> None:
    evidence = [
        make_evidence("e1", field="measure", value="4"),
        make_evidence("e2", field="measure", value="0"),
    ]
    result = call_calculator(
        [
            {
                "calculation_id": "zero-denominator",
                "operation": "ratio",
                "operands": [operand(4, "km", "e1", "measure"), operand(0, "s", "e2", "measure")],
            }
        ],
        evidence,
    )

    assert result.status is ToolStatus.FAILED
    assert "cannot be zero" in (result.message or "")
    assert result.evidence == ()


def test_percentage_change_rejects_zero_baseline() -> None:
    evidence = [
        make_evidence("e1", field="measure", value="0"),
        make_evidence("e2", field="measure", value="4"),
    ]
    result = call_calculator(
        [
            {
                "calculation_id": "zero-baseline",
                "operation": "percentage_change",
                "operands": [operand(0, "count", "e1", "measure"), operand(4, "count", "e2", "measure")],
            }
        ],
        evidence,
    )

    assert result.status is ToolStatus.FAILED
    assert "baseline cannot be zero" in (result.message or "")


def test_calculator_rejects_value_that_does_not_match_source_record() -> None:
    evidence = [make_evidence("e1", field="measurement", value="12.5")]
    result = call_calculator(
        [
            {
                "calculation_id": "fabricated-value",
                "operation": "difference",
                "operands": [
                    operand(999, "km", "e1", "measurement"),
                    operand(2, "km", "e1", "measurement"),
                ],
            }
        ],
        evidence,
    )

    assert result.status is ToolStatus.FAILED
    assert "does not match" in (result.message or "")


def test_calculator_rejects_unknown_evidence_id() -> None:
    evidence = [make_evidence("e1", field="measurement", value="3")]
    result = call_calculator(
        [
            {
                "calculation_id": "unknown-source",
                "operation": "difference",
                "operands": [
                    operand(3, "km", "missing", "measurement"),
                    operand(2, "km", "e1", "measurement"),
                ],
            }
        ],
        evidence,
    )

    assert result.status is ToolStatus.FAILED
    assert "unknown evidence ID" in (result.message or "")


def test_calculator_rejects_field_not_selected_in_evidence() -> None:
    evidence = [make_evidence("e1", field="selected_field", value="3")]
    result = call_calculator(
        [
            {
                "calculation_id": "wrong-field",
                "operation": "difference",
                "operands": [
                    operand(3, "km", "e1", "other_field"),
                    operand(2, "km", "e1", "selected_field"),
                ],
            }
        ],
        evidence,
    )

    assert result.status is ToolStatus.FAILED
    assert "not selected" in (result.message or "")


def test_calculator_rejects_non_json_record_evidence() -> None:
    evidence = EvidenceReference(
        evidence_id="text-evidence",
        source_id="document-1",
        title="A paragraph",
        excerpt="The measurement is 4 km.",
    )
    result = call_calculator(
        [
            {
                "calculation_id": "not-a-record",
                "operation": "difference",
                "operands": [
                    operand(4, "km", "text-evidence", "measurement"),
                    operand(2, "km", "text-evidence", "measurement"),
                ],
            }
        ],
        [evidence],
    )

    assert result.status is ToolStatus.FAILED
    assert "structured JSON record" in (result.message or "")


def test_calculator_rejects_duplicate_calculation_ids_atomically() -> None:
    evidence = [
        make_evidence("e1", field="measurement", value="4"),
        make_evidence("e2", field="measurement", value="2"),
    ]
    one_calc = {
        "calculation_id": "duplicate",
        "operation": "difference",
        "operands": [operand(4, "km", "e1", "measurement"), operand(2, "km", "e2", "measurement")],
    }
    result = call_calculator([one_calc, one_calc], evidence)

    assert result.status is ToolStatus.FAILED
    assert result.evidence == ()
    assert "Duplicate calculation_id" in (result.message or "")


def test_operation_registry_can_be_extended_without_agent_source_changes() -> None:
    registry = create_default_operation_registry()
    registry.register(
        CalculationOperation(
            "twice_difference",
            "Return twice the difference of two compatible measurements.",
            2,
            2,
            lambda values, units: (
                (values[0] - values[1]) * Decimal(2),
                units[0] if len(set(units)) == 1 else _incompatible_units(),
            ),
        )
    )
    calculator = QuantitativeCalculatorTool(operation_registry=registry)
    evidence = [
        make_evidence("e1", field="measurement", value="7"),
        make_evidence("e2", field="measurement", value="2"),
    ]
    result = call_calculator(
        [
            {
                "calculation_id": "custom-op",
                "operation": "twice_difference",
                "operands": [operand(7, "km", "e1", "measurement"), operand(2, "km", "e2", "measurement")],
            }
        ],
        evidence,
        tool=calculator,
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.data["calculations"][0]["value"] == 10.0
    assert "twice_difference" in calculator.descriptor.input_schema["properties"]["calculations"]["items"]["properties"]["operation"]["enum"]


def test_registry_supports_single_operand_custom_operations() -> None:
    registry = CalculationOperationRegistry(
        (
            CalculationOperation(
                "negate",
                "Negate one numeric value.",
                1,
                1,
                lambda values, units: (-values[0], units[0]),
            ),
        )
    )
    calculator = QuantitativeCalculatorTool(operation_registry=registry)
    evidence = [make_evidence("e1", field="measurement", value="4")]
    result = call_calculator(
        [
            {
                "calculation_id": "negative",
                "operation": "negate",
                "operands": [operand(4, "km", "e1", "measurement")],
            }
        ],
        evidence,
        tool=calculator,
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.data["calculations"][0]["value"] == -4.0


def _incompatible_units() -> str:
    """Fail a custom operation when its supplied units are incompatible."""
    raise ValueError("twice_difference requires compatible unit labels.")


def test_calculator_preserves_exact_decimal_strings_from_source_records() -> None:
    evidence = [
        make_evidence("precise-a", field="measurement", value="8.5000000000000001"),
        make_evidence("precise-b", field="measurement", value="3.25"),
    ]
    result = call_calculator(
        [
            {
                "calculation_id": "precise-difference",
                "operation": "difference",
                "operands": [
                    operand("8.5000000000000001", "km", "precise-a", "measurement"),
                    operand("3.25", "km", "precise-b", "measurement"),
                ],
            }
        ],
        evidence,
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.data["calculations"][0]["value_exact"] == "5.2500000000000001"
