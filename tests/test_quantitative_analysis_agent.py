"""Tests for the evidence-gated Quantitative Analysis Agent."""

from __future__ import annotations

import json
from typing import Any

from exotrace.agents.contracts import AgentStatus, AgentTask
from exotrace.agents.quantitative_analysis import QuantitativeAnalysisAgent
from exotrace.agents.quantitative_assembly import build_quantitative_analysis_layer
from exotrace.contracts import EvidenceReference
from exotrace.tools.quantitative_calculator import (
    CalculationOperation,
    create_default_operation_registry,
)
from decimal import Decimal


def source_record(
    evidence_id: str,
    *,
    field: str,
    value: str,
    record_id: str,
    producer_task_key: str,
) -> EvidenceReference:
    """Build a source record where the requested numeric field is explicit and traceable."""
    return EvidenceReference(
        evidence_id=evidence_id,
        source_id=f"source::{record_id}",
        title=f"Catalogue row for {record_id}",
        excerpt=json.dumps({field: value}),
        source_uri="https://example.invalid/catalogue",
        source_kind="test_catalogue_record",
        snapshot_id="snapshot-test",
        record_id=record_id,
        metadata={
            "selected_fields": [field],
            "source_table": "test",
            "exotrace_producer_task_key": producer_task_key,
            "declared_unit": "km",
        },
    )


def calculation_context() -> dict[str, Any]:
    """Return one calculation using explicit source-evidence references."""
    return {
        "calculations": [
            {
                "calculation_id": "measured-difference",
                "operation": "difference",
                "operands": [
                    {"source_task_key": "lookup-a", "field": "measurement"},
                    {"source_task_key": "lookup-b", "field": "measurement"},
                ],
            }
        ]
    }


def source_evidence() -> tuple[EvidenceReference, ...]:
    """Return source evidence corresponding exactly to calculation_context()."""
    return (
        source_record(
            "evidence-a",
            field="measurement",
            value="8.5",
            record_id="record-a",
            producer_task_key="lookup-a",
        ),
        source_record(
            "evidence-b",
            field="measurement",
            value="3.25",
            record_id="record-b",
            producer_task_key="lookup-b",
        ),
    )


def make_task(agent: QuantitativeAnalysisAgent, *, evidence: tuple[EvidenceReference, ...] | None = None) -> AgentTask:
    """Build an explicit quantitative task using its registered tool permission."""
    return AgentTask(
        task_id="quantitative-task-1",
        question="Calculate the difference between two measurements.",
        objective="Calculate the specified difference using the supplied source records.",
        required_capabilities=(agent.CAPABILITY_ID,),
        allowed_tool_ids=(agent.descriptor.allowed_tool_ids[0],),
        input_evidence=source_evidence() if evidence is None else evidence,
        context=calculation_context(),
    )


def test_quantitative_agent_executes_only_registered_deterministic_calculation() -> None:
    agent_registry, tool_registry = build_quantitative_analysis_layer()
    agent = agent_registry.get(QuantitativeAnalysisAgent.AGENT_ID)
    task = make_task(agent)
    executor = tool_registry.executor_for(agent.descriptor, task)

    result = agent.run(task, tools=executor)

    assert result.status is AgentStatus.SUCCEEDED
    assert len(result.findings) == 1
    assert result.findings[0].statement == "measured-difference = 5.25 km"
    assert len(result.evidence) == 3
    derived = result.evidence[-1]
    assert derived.evidence_id in result.findings[0].evidence_ids
    assert derived.metadata["input_evidence_ids"] == ["evidence-a", "evidence-b"]
    assert result.tool_ids_used == (agent.descriptor.allowed_tool_ids[0],)


def test_quantitative_agent_refuses_values_without_source_evidence() -> None:
    agent_registry, tool_registry = build_quantitative_analysis_layer()
    agent = agent_registry.get(QuantitativeAnalysisAgent.AGENT_ID)
    task = make_task(agent, evidence=())

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.INSUFFICIENT_EVIDENCE
    assert not result.findings
    assert result.tool_ids_used == ()


def test_quantitative_agent_fails_when_source_field_is_missing_from_dependency_evidence() -> None:
    agent_registry, tool_registry = build_quantitative_analysis_layer()
    agent = agent_registry.get(QuantitativeAnalysisAgent.AGENT_ID)
    context = calculation_context()
    context["calculations"][0]["operands"][0]["field"] = "missing_measurement"
    task = AgentTask(
        task_id="quantitative-task-missing-field",
        question="Calculate a difference.",
        objective="Calculate a difference from dependency records.",
        required_capabilities=(agent.CAPABILITY_ID,),
        allowed_tool_ids=agent.descriptor.allowed_tool_ids,
        input_evidence=source_evidence(),
        context=context,
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "calculation_operand_resolution_failed"
    assert "No numeric source field" in (result.error_message or "")


def test_quantitative_agent_descriptor_uses_live_operation_registry() -> None:
    operation_registry = create_default_operation_registry()
    operation_registry.register(
        CalculationOperation(
            "custom_average_of_two",
            "A custom test-only mean implementation.",
            2,
            2,
            lambda values, units: ((values[0] + values[1]) / Decimal(2), units[0]),
        )
    )
    agent_registry, _tool_registry = build_quantitative_analysis_layer(
        operation_registry=operation_registry
    )
    agent = agent_registry.get(QuantitativeAnalysisAgent.AGENT_ID)
    operation_enum = agent.descriptor.task_context_schema["properties"]["calculations"]["items"]["properties"]["operation"]["enum"]

    assert "custom_average_of_two" in operation_enum


def test_quantitative_layer_is_separate_from_default_three_agent_assembly() -> None:
    quant_agents, quant_tools = build_quantitative_analysis_layer()

    assert [item.agent_id for item in quant_agents.descriptors()] == ["quantitative_analysis"]
    assert [item.tool_id for item in quant_tools.descriptors()] == ["quantitative.calculate"]


def test_agent_task_without_allowed_calculator_tool_is_rejected() -> None:
    agent_registry, tool_registry = build_quantitative_analysis_layer()
    agent = agent_registry.get(QuantitativeAnalysisAgent.AGENT_ID)
    task = AgentTask(
        task_id="quantitative-no-permission",
        question="Calculate a difference.",
        objective="Calculate a difference.",
        required_capabilities=(agent.CAPABILITY_ID,),
        allowed_tool_ids=(),
        input_evidence=source_evidence(),
        context=calculation_context(),
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "task_tool_not_granted"


def test_quantitative_agent_does_not_accept_unregistered_capability() -> None:
    agent_registry, tool_registry = build_quantitative_analysis_layer()
    agent = agent_registry.get(QuantitativeAnalysisAgent.AGENT_ID)
    task = AgentTask(
        task_id="quantitative-unknown-capability",
        question="Calculate a difference.",
        objective="Calculate a difference.",
        required_capabilities=("catalogue.rewrite",),
        allowed_tool_ids=agent.descriptor.allowed_tool_ids,
        input_evidence=source_evidence(),
        context=calculation_context(),
    )

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "unsupported_capability"


def test_quantitative_agent_context_schema_disallows_extra_operand_fields() -> None:
    agent_registry, _tool_registry = build_quantitative_analysis_layer()
    agent = agent_registry.get(QuantitativeAnalysisAgent.AGENT_ID)
    operand_schema = agent.descriptor.task_context_schema["properties"]["calculations"]["items"]["properties"]["operands"]["items"]

    assert operand_schema["additionalProperties"] is False
    assert set(operand_schema["required"]) == {"source_task_key", "field"}


def test_quantitative_agent_refuses_ambiguous_source_task_output() -> None:
    agent_registry, tool_registry = build_quantitative_analysis_layer()
    agent = agent_registry.get(QuantitativeAnalysisAgent.AGENT_ID)
    evidence = (
        source_record(
            "evidence-a1", field="measurement", value="8.5", record_id="record-a1",
            producer_task_key="lookup-a",
        ),
        source_record(
            "evidence-a2", field="measurement", value="9.5", record_id="record-a2",
            producer_task_key="lookup-a",
        ),
        source_record(
            "evidence-b", field="measurement", value="3.25", record_id="record-b",
            producer_task_key="lookup-b",
        ),
    )
    task = make_task(agent, evidence=evidence)

    result = agent.run(task, tools=tool_registry.executor_for(agent.descriptor, task))

    assert result.status is AgentStatus.FAILED
    assert result.error_code == "calculation_operand_resolution_failed"
    assert "ambiguous" in (result.error_message or "")
