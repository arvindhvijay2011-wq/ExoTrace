"""Specialist-agent contracts, registries, planning, synthesis, and orchestration exports."""

from __future__ import annotations

from typing import Any

from exotrace.agents.contracts import (
    AgentDescriptor,
    AgentResult,
    AgentStatus,
    AgentTask,
    SpecialistAgent,
)
from exotrace.agents.registry import AgentRegistry, AgentRegistryError

__all__ = [
    "AgentDescriptor",
    "AgentRegistry",
    "AgentRegistryError",
    "AgentResult",
    "AgentStatus",
    "AgentTask",
    "AnswerSynthesisAgent",
    "AnswerSynthesisError",
    "SynthesisResult",
    "InvestigationOrchestrator",
    "LangGraphDependencyError",
    "LangGraphInvestigationWorkflow",
    "InvestigationPlan",
    "InvestigationReport",
    "InvestigationStatus",
    "LiteratureDefinitionAgent",
    "CatalogueDataAgent",
    "GraphInvestigationAgent",
    "OpenAIResponsesTaskPlanner",
    "OrchestrationError",
    "OrchestratorConfig",
    "PlanDisposition",
    "QuantitativeAnalysisAgent",
    "build_quantitative_analysis_layer",
    "PlannedAgentTask",
    "PlannerError",
    "SpecialistAgent",
    "TaskPlanner",
    "build_initial_specialist_layer",
    "build_specialist_layer",
    "validate_context_against_schema",
]


def __getattr__(name: str) -> Any:
    """Import implementation modules lazily to avoid cross-package import cycles."""
    if name in {"AnswerSynthesisAgent", "AnswerSynthesisError", "SynthesisResult"}:
        from exotrace.agents.synthesis import (
            AnswerSynthesisAgent,
            AnswerSynthesisError,
            SynthesisResult,
        )

        return {
            "AnswerSynthesisAgent": AnswerSynthesisAgent,
            "AnswerSynthesisError": AnswerSynthesisError,
            "SynthesisResult": SynthesisResult,
        }[name]
    if name in {"LangGraphDependencyError", "LangGraphInvestigationWorkflow"}:
        from exotrace.agents.langgraph_workflow import (
            LangGraphDependencyError,
            LangGraphInvestigationWorkflow,
        )

        return {
            "LangGraphDependencyError": LangGraphDependencyError,
            "LangGraphInvestigationWorkflow": LangGraphInvestigationWorkflow,
        }[name]
    if name == "CatalogueDataAgent":
        from exotrace.agents.catalogue_data import CatalogueDataAgent

        return CatalogueDataAgent
    if name == "GraphInvestigationAgent":
        from exotrace.agents.graph_investigation import GraphInvestigationAgent

        return GraphInvestigationAgent
    if name == "LiteratureDefinitionAgent":
        from exotrace.agents.literature_definition import LiteratureDefinitionAgent

        return LiteratureDefinitionAgent
    if name in {"build_initial_specialist_layer", "build_specialist_layer"}:
        from exotrace.agents.assembly import (
            build_initial_specialist_layer,
            build_specialist_layer,
        )

        return {
            "build_initial_specialist_layer": build_initial_specialist_layer,
            "build_specialist_layer": build_specialist_layer,
        }[name]
    if name == "QuantitativeAnalysisAgent":
        from exotrace.agents.quantitative_analysis import QuantitativeAnalysisAgent

        return QuantitativeAnalysisAgent
    if name == "build_quantitative_analysis_layer":
        from exotrace.agents.quantitative_assembly import build_quantitative_analysis_layer

        return build_quantitative_analysis_layer
    if name in {
        "InvestigationPlan",
        "OpenAIResponsesTaskPlanner",
        "PlanDisposition",
        "PlannedAgentTask",
        "PlannerError",
        "TaskPlanner",
    }:
        from exotrace.agents.planning import (
            InvestigationPlan,
            OpenAIResponsesTaskPlanner,
            PlanDisposition,
            PlannedAgentTask,
            PlannerError,
            TaskPlanner,
        )

        return {
            "InvestigationPlan": InvestigationPlan,
            "OpenAIResponsesTaskPlanner": OpenAIResponsesTaskPlanner,
            "PlanDisposition": PlanDisposition,
            "PlannedAgentTask": PlannedAgentTask,
            "PlannerError": PlannerError,
            "TaskPlanner": TaskPlanner,
        }[name]
    if name in {
        "InvestigationOrchestrator",
    "LangGraphDependencyError",
    "LangGraphInvestigationWorkflow",
        "InvestigationReport",
        "InvestigationStatus",
        "OrchestrationError",
        "OrchestratorConfig",
        "validate_context_against_schema",
    }:
        from exotrace.agents.orchestrator import (
            InvestigationOrchestrator,
            InvestigationReport,
            InvestigationStatus,
            OrchestrationError,
            OrchestratorConfig,
            validate_context_against_schema,
        )

        return {
            "InvestigationOrchestrator": InvestigationOrchestrator,
            "InvestigationReport": InvestigationReport,
            "InvestigationStatus": InvestigationStatus,
            "OrchestrationError": OrchestrationError,
            "OrchestratorConfig": OrchestratorConfig,
            "validate_context_against_schema": validate_context_against_schema,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
