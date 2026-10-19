"""Build a focused Quantitative Analysis Agent/calculator registry for direct tests and embedding.

The normal investigation workflow registers this agent through ``build_specialist_layer``.
This separate factory remains useful for testing the calculator boundary without constructing
the literature, catalogue, graph, or planner layers.
"""

from __future__ import annotations

from exotrace.agents.quantitative_analysis import QuantitativeAnalysisAgent
from exotrace.agents.registry import AgentRegistry
from exotrace.tools.quantitative_calculator import (
    CalculationOperationRegistry,
    QuantitativeCalculatorTool,
)
from exotrace.tools.registry import ToolRegistry


def build_quantitative_analysis_layer(
    *,
    operation_registry: CalculationOperationRegistry | None = None,
) -> tuple[AgentRegistry, ToolRegistry]:
    """Build a standalone quantitative agent/tool pair for focused execution or tests.

    Production investigations use ``build_specialist_layer`` so that the quantitative agent
    participates in dependency-aware plans and receives evidence only from declared upstream
    tasks. This small factory is retained to isolate the agent/tool contract in unit tests.
    """
    calculator = QuantitativeCalculatorTool(operation_registry=operation_registry)
    agent = QuantitativeAnalysisAgent(calculator_tool=calculator)
    return AgentRegistry((agent,)), ToolRegistry((calculator,))
