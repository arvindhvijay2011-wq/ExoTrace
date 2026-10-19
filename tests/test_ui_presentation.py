"""Tests for readable, source-derived UI presentation of deterministic calculations."""

from __future__ import annotations

from typing import Any

from exotrace.ui.presentation import (
    calculation_answer_statements,
    calculation_summaries,
    format_numeric_value,
    planned_calculation_formulas,
)


def _report(*, reverse_operands: bool = False) -> dict[str, Any]:
    b_task = {
        "task_key": "lookup_b",
        "agent_id": "catalogue_data",
        "question": "Retrieve radius for Kepler-10 b.",
        "context": {"filters": {"pl_name": "Kepler-10 b"}, "fields": ["pl_name", "pl_rade"]},
    }
    c_task = {
        "task_key": "lookup_c",
        "agent_id": "catalogue_data",
        "question": "Retrieve radius for Kepler-10 c.",
        "context": {"filters": [{"field": "pl_name", "value": "Kepler-10 c"}], "fields": ["pl_name", "pl_rade"]},
    }
    operands = [
        {"source_task_key": "lookup_c", "field": "pl_rade"},
        {"source_task_key": "lookup_b", "field": "pl_rade"},
    ]
    if reverse_operands:
        operands.reverse()
    return {
        "plan": {
            "tasks": [
                b_task,
                c_task,
                {
                    "task_key": "ratio_task",
                    "agent_id": "quantitative_analysis",
                    "context": {
                        "calculations": [
                            {"calculation_id": "radius_ratio", "operation": "ratio", "operands": operands}
                        ]
                    },
                },
            ]
        },
        "results": [
            {
                "agent_id": "catalogue_data",
                "evidence": [
                    {
                        "evidence_id": "catalogue:b",
                        "excerpt": '{"pl_name":"Kepler-10 b","pl_rade":"1.47"}',
                    },
                    {
                        "evidence_id": "catalogue:c",
                        "excerpt": '{"pl_name":"Kepler-10 c","pl_rade":"2.355"}',
                    },
                ],
                "findings": [],
            },
            {
                "agent_id": "quantitative_analysis",
                "findings": [
                    {
                        "statement": "radius_ratio = 1.602040816326530612244897959 1",
                        "finding_type": "derived_quantitative_result",
                        "evidence_ids": ["calculation:evidence-3"],
                        "data": {
                            "calculation_id": "radius_ratio",
                            "operation": "ratio",
                            "value": 1.6020408163265306,
                            "value_exact": "1.602040816326530612244897959",
                            "unit": "1",
                            "input_evidence_ids": ["catalogue:c", "catalogue:b"],
                            "input_source_ids": ["record:c", "record:b"],
                            "input_fields": ["pl_rade", "pl_rade"],
                            "input_units": ["source-native", "source-native"],
                        },
                    }
                ],
            }
        ],
    }


def test_calculation_summary_displays_explicit_numerator_and_denominator() -> None:
    summaries = calculation_summaries(_report())

    assert len(summaries) == 1
    assert summaries[0]["formula"] == "Kepler-10 c · pl_rade ÷ Kepler-10 b · pl_rade"
    assert summaries[0]["value_display"] == "1.602041"
    assert summaries[0]["value_exact"] == "1.602040816326530612244897959"
    assert summaries[0]["unit"] == "1"
    assert summaries[0]["input_source_ids"] == ["record:c", "record:b"]
    assert summaries[0]["input_values"] == [
        {
            "label": "Kepler-10 c · pl_rade",
            "field": "pl_rade",
            "value": "2.355",
            "evidence_id": "catalogue:c",
        },
        {
            "label": "Kepler-10 b · pl_rade",
            "field": "pl_rade",
            "value": "1.47",
            "evidence_id": "catalogue:b",
        },
    ]


def test_reversing_saved_plan_operands_reverses_displayed_formula() -> None:
    summaries = calculation_summaries(_report(reverse_operands=True))

    assert summaries[0]["formula"] == "Kepler-10 b · pl_rade ÷ Kepler-10 c · pl_rade"


def test_non_calculation_report_has_no_calculation_highlights() -> None:
    assert calculation_summaries({"plan": {"tasks": []}, "results": []}) == []


def test_numeric_formatting_preserves_small_values_and_exact_input_elsewhere() -> None:
    assert format_numeric_value("0.0000000012345") == "1.2345e-9"
    assert format_numeric_value("not-numeric") == "not-numeric"
    assert format_numeric_value(True) == "True"


def test_plan_preview_exposes_formula_order_before_execution() -> None:
    formulas = planned_calculation_formulas(_report())

    assert formulas == [
        {
            "calculation_id": "radius_ratio",
            "title": "Calculated ratio",
            "operation": "ratio",
            "formula": "Kepler-10 c · pl_rade ÷ Kepler-10 b · pl_rade",
        }
    ]


def test_answer_first_sentence_uses_declared_ratio_direction() -> None:
    statements = calculation_answer_statements(_report())

    assert len(statements) == 1
    assert statements[0]["text"] == (
        "The ratio of Kepler-10 c (pl_rade) to Kepler-10 b (pl_rade) is **1.602041**."
    )
    assert statements[0]["formula"] == "Kepler-10 c · pl_rade ÷ Kepler-10 b · pl_rade"


def test_answer_first_sentence_is_empty_without_calculation_results() -> None:
    assert calculation_answer_statements({"plan": {"tasks": []}, "results": []}) == []
