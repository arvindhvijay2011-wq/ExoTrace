"""Pure presentation helpers for compact, provenance-aware ExoTrace UI views."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

_OPERATION_SYMBOLS: dict[str, str] = {
    "ratio": "÷",
    "difference": "−",
    "subtract": "−",
    "sum": "+",
    "add": "+",
    "product": "×",
    "multiply": "×",
}

_OPERATION_TITLES: dict[str, str] = {
    "ratio": "Calculated ratio",
    "difference": "Calculated difference",
    "subtract": "Calculated difference",
    "sum": "Calculated sum",
    "add": "Calculated sum",
    "product": "Calculated product",
    "multiply": "Calculated product",
    "mean": "Calculated mean",
    "average": "Calculated mean",
    "percentage_change": "Percentage change",
}


def format_numeric_value(value: Any, *, significant_digits: int = 7) -> str:
    """Return a readable numeric representation without discarding the exact source value."""
    if isinstance(value, bool) or significant_digits < 1:
        return str(value)
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    return format(number, f".{significant_digits}g")


def _task_label(task: Mapping[str, Any]) -> str:
    """Choose a compact, grounded label from explicit lookup filters or the task contract."""
    context = task.get("context")
    filters = context.get("filters") if isinstance(context, Mapping) else None
    if isinstance(filters, Mapping):
        for key in ("pl_name", "hostname", "object_name", "planet_name", "name"):
            value = filters.get(key)
            if isinstance(value, str) and value.strip() and value.strip().lower() != "null":
                return value.strip()
        if isinstance(filters, list):
            for item in filters:
                if not isinstance(item, Mapping):
                    continue
                field = item.get("field")
                value = item.get("value")
                if field in {"pl_name", "hostname", "object_name", "planet_name", "name"} and isinstance(value, str) and value.strip():
                    return value.strip()
    if isinstance(filters, list):
        for item in filters:
            if not isinstance(item, Mapping):
                continue
            field = item.get("field")
            value = item.get("value")
            if field in {"pl_name", "hostname", "object_name", "planet_name", "name"} and isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("objective", "question", "task_key"):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip(".")
    return "Upstream record"


def _display_operand(operand: Mapping[str, Any], task_by_key: Mapping[str, Mapping[str, Any]]) -> str:
    """Render one symbolic operand without replacing it with an unverified value."""
    task_key = operand.get("source_task_key")
    field_name = operand.get("field")
    source_task = task_by_key.get(task_key) if isinstance(task_key, str) else None
    label = _task_label(source_task) if source_task else (task_key or "source")
    if isinstance(field_name, str) and field_name.strip():
        return f"{label} · {field_name.strip()}"
    return str(label)



def planned_calculation_formulas(report: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build a preview of symbolic calculation order from the reviewed task plan."""
    raw_plan = report.get("plan")
    tasks = raw_plan.get("tasks", []) if isinstance(raw_plan, Mapping) else []
    if not isinstance(tasks, list):
        return []
    task_by_key = {
        str(task["task_key"]): task
        for task in tasks
        if isinstance(task, Mapping) and isinstance(task.get("task_key"), str)
    }
    formulas: list[dict[str, str]] = []
    for task in tasks:
        if not isinstance(task, Mapping) or task.get("agent_id") != "quantitative_analysis":
            continue
        context = task.get("context")
        calculations = context.get("calculations", []) if isinstance(context, Mapping) else []
        if not isinstance(calculations, list):
            continue
        for calculation in calculations:
            if not isinstance(calculation, Mapping):
                continue
            operation = str(calculation.get("operation") or "calculation")
            operands = calculation.get("operands", [])
            if not isinstance(operands, list):
                operands = []
            operand_labels = [
                _display_operand(operand, task_by_key)
                for operand in operands
                if isinstance(operand, Mapping)
            ]
            symbol = _OPERATION_SYMBOLS.get(operation, f" {operation} ")
            formula = f" {symbol} ".join(operand_labels) if operand_labels else "Formula not specified"
            formulas.append(
                {
                    "calculation_id": str(calculation.get("calculation_id") or "calculation"),
                    "title": _OPERATION_TITLES.get(operation, operation.replace("_", " ").capitalize()),
                    "operation": operation,
                    "formula": formula,
                }
            )
    return formulas

def calculation_summaries(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pair deterministic findings with their declared symbolic operands and source labels."""
    raw_plan = report.get("plan")
    tasks = raw_plan.get("tasks", []) if isinstance(raw_plan, Mapping) else []
    if not isinstance(tasks, list):
        tasks = []
    task_by_key = {
        str(task["task_key"]): task
        for task in tasks
        if isinstance(task, Mapping) and isinstance(task.get("task_key"), str)
    }

    specs: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, Mapping) or task.get("agent_id") != "quantitative_analysis":
            continue
        context = task.get("context")
        calculations = context.get("calculations", []) if isinstance(context, Mapping) else []
        if not isinstance(calculations, list):
            continue
        for calculation in calculations:
            if isinstance(calculation, Mapping) and isinstance(calculation.get("calculation_id"), str):
                specs[calculation["calculation_id"]] = dict(calculation)

    found: list[dict[str, Any]] = []
    results = report.get("results", [])
    if not isinstance(results, list):
        return found

    # The catalogue agents' source excerpts contain the selected raw field/value pairs.
    # Index only returned evidence so displayed input values remain traceable to the report.
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            continue
        evidence_items = result.get("evidence", [])
        if not isinstance(evidence_items, list):
            continue
        for evidence_item in evidence_items:
            if isinstance(evidence_item, Mapping) and isinstance(evidence_item.get("evidence_id"), str):
                evidence_by_id[evidence_item["evidence_id"]] = evidence_item

    for result in results:
        if not isinstance(result, Mapping) or result.get("agent_id") != "quantitative_analysis":
            continue
        findings = result.get("findings", [])
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, Mapping):
                continue
            data = finding.get("data")
            if not isinstance(data, Mapping) or not data.get("calculation_id"):
                continue
            calculation_id = str(data["calculation_id"])
            spec = specs.get(calculation_id, {})
            operation = str(data.get("operation") or spec.get("operation") or "calculation")
            operands = spec.get("operands", [])
            if not isinstance(operands, list):
                operands = []
            operand_labels = [
                _display_operand(operand, task_by_key)
                for operand in operands
                if isinstance(operand, Mapping)
            ]
            symbol = _OPERATION_SYMBOLS.get(operation, f" {operation} ")
            formula = f" {symbol} ".join(operand_labels) if operand_labels else "Formula recorded in source report"
            exact_value = data.get("value_exact", data.get("value", "Not returned"))
            unit = str(data.get("unit", "unspecified"))
            title = _OPERATION_TITLES.get(operation, operation.replace("_", " ").capitalize())
            evidence_ids = finding.get("evidence_ids", [])
            input_source_ids = list(data.get("input_source_ids", [])) if isinstance(data.get("input_source_ids"), list) else []
            input_evidence_ids = list(data.get("input_evidence_ids", [])) if isinstance(data.get("input_evidence_ids"), list) else []
            input_fields = list(data.get("input_fields", [])) if isinstance(data.get("input_fields"), list) else []
            input_values: list[dict[str, str]] = []
            for operand_index, field_name in enumerate(input_fields):
                if not isinstance(field_name, str):
                    continue
                evidence_id = input_evidence_ids[operand_index] if operand_index < len(input_evidence_ids) else None
                source_evidence = evidence_by_id.get(evidence_id) if isinstance(evidence_id, str) else None
                excerpt = source_evidence.get("excerpt") if isinstance(source_evidence, Mapping) else None
                if not isinstance(excerpt, str) or not excerpt.strip():
                    continue
                try:
                    raw_values = json.loads(excerpt)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw_values, Mapping) or raw_values.get(field_name) is None:
                    continue
                label = operand_labels[operand_index] if operand_index < len(operand_labels) else field_name
                input_values.append(
                    {
                        "label": str(label),
                        "field": field_name,
                        "value": str(raw_values[field_name]),
                        "evidence_id": evidence_id,
                    }
                )

            found.append(
                {
                    "calculation_id": calculation_id,
                    "title": title,
                    "operation": operation,
                    "formula": formula,
                    "value_display": format_numeric_value(exact_value),
                    "value_exact": str(exact_value),
                    "unit": unit,
                    "input_source_ids": input_source_ids,
                    "input_evidence_ids": input_evidence_ids,
                    "input_fields": input_fields,
                    "input_values": input_values,
                    "derived_evidence_ids": [str(item) for item in evidence_ids] if isinstance(evidence_ids, list) else [],
                }
            )
    return found


def calculation_answer_statements(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build concise answer text directly from deterministic calculation evidence.

    The statement follows the operand order declared in the saved plan. This makes the
    UI's answer direction explicit and avoids a second language-model rewrite accidentally
    reversing a numerator and denominator.
    """
    statements: list[dict[str, Any]] = []
    for item in calculation_summaries(report):
        formula = str(item.get("formula", "Formula not recorded"))
        operation = str(item.get("operation", "calculation")).casefold()
        value = str(item.get("value_display", "Not returned"))
        unit = str(item.get("unit", "unspecified"))
        value_text = value if unit in {"1", "", "unspecified", "None"} else f"{value} {unit}"

        if operation == "ratio" and " ÷ " in formula:
            numerator, denominator = formula.split(" ÷ ", 1)
            numerator_label = _friendly_operand_label(numerator)
            denominator_label = _friendly_operand_label(denominator)
            text = f"The ratio of {numerator_label} to {denominator_label} is **{value_text}**."
        else:
            title = str(item.get("title") or "Calculated result")
            text = f"{title}: **{value_text}**."

        statements.append({**item, "text": text})
    return statements


def _friendly_operand_label(label: str) -> str:
    """Render the internal entity/field separator as compact reader-facing text."""
    if " · " in label:
        entity, field_name = label.rsplit(" · ", 1)
        return f"{entity} ({field_name})"
    return label

def reader_friendly_source_title(title: str) -> str:
    """Remove generic record-type suffixes from source titles shown in the answer."""
    cleaned = " ".join(title.split()).strip()
    if not cleaned:
        return "Source"
    suffixes = (" catalogue record", " catalog record")
    for suffix in suffixes:
        if cleaned.casefold().endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip()
            break
    return cleaned or "Source"


def group_answer_claims(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Group claim-level statements by their shared evidence for compact UI rendering.

    Claims supported by the same catalogue record are shown together, avoiding a repeated
    evidence label after every individual property. The helper does not merge or rewrite
    scientific statements; it only groups them by their declared citation IDs.
    """
    raw_answer = payload.get("answer")
    answer = raw_answer if isinstance(raw_answer, Mapping) else payload
    claims = answer.get("claims", [])
    raw_evidence = answer.get("evidence", [])
    if not isinstance(claims, list):
        return []

    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            if isinstance(item, Mapping) and isinstance(item.get("evidence_id"), str):
                evidence_by_id[item["evidence_id"]] = item

    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        statement = claim.get("text")
        if not isinstance(statement, str) or not statement.strip():
            continue
        raw_ids = claim.get("evidence_ids", [])
        evidence_values = raw_ids if isinstance(raw_ids, list) else []
        evidence_ids = tuple(dict.fromkeys(
            value.strip() for value in evidence_values
            if isinstance(value, str) and value.strip()
        ))
        key = evidence_ids or ("__uncited__",)
        group = grouped.get(key)
        if group is None:
            titles = [
                str(evidence_by_id[evidence_id].get("title") or evidence_by_id[evidence_id].get("doc_id") or evidence_id)
                for evidence_id in evidence_ids if evidence_id in evidence_by_id
            ]
            if len(titles) == 1:
                # Preserve the original evidence title in this helper's return contract.
                # The UI may format the title for display at its rendering boundary.
                title = titles[0]
            elif len(titles) > 1:
                title = "Finding supported by multiple sources"
            else:
                title = "Finding"
            group = {"title": title, "evidence_ids": list(evidence_ids), "claims": []}
            grouped[key] = group
        group["claims"].append(statement.strip())

    groups = list(grouped.values())
    for group in groups:
        group["text"] = " ".join(group["claims"])
    return groups
