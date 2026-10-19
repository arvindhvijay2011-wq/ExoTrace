"""Construct bounded ExoTrace specialist layers without question-routing logic."""

from __future__ import annotations

from typing import Any, Protocol

from exotrace.agents.catalogue_data import CatalogueDataAgent
from exotrace.agents.graph_investigation import GraphInvestigationAgent
from exotrace.agents.literature_definition import LiteratureDefinitionAgent
from exotrace.agents.quantitative_analysis import QuantitativeAnalysisAgent
from exotrace.agents.registry import AgentRegistry
from exotrace.tools.catalogue_lookup import CatalogueLookupConfig, CatalogueRecordLookupTool
from exotrace.tools.graph_investigation import GraphInvestigationConfig, GraphInvestigationTool
from exotrace.tools.literature_search import LiteratureSearchConfig, LiteratureSearchTool
from exotrace.tools.quantitative_calculator import QuantitativeCalculatorTool
from exotrace.tools.registry import ToolRegistry


class SearchRetriever(Protocol):
    """Structural interface to the existing HybridTextRetriever."""

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        scope: str = "references",
        strategy: str = "dense",
    ) -> list[dict[str, Any]]:
        """Search the configured frozen vector corpus."""
        ...


class GraphDriver(Protocol):
    """Structural interface accepted by the graph investigation tool."""

    def session(self, *, database: str) -> Any:
        """Open a Neo4j session for the specified database."""
        ...


def build_initial_specialist_layer(
    retriever: SearchRetriever,
    *,
    literature_config: LiteratureSearchConfig | None = None,
    catalogue_config: CatalogueLookupConfig | None = None,
) -> tuple[AgentRegistry, ToolRegistry]:
    """Register the original Literature and Catalogue specialists, preserving old behavior."""
    literature_tool = LiteratureSearchTool(retriever, config=literature_config)
    catalogue_tool = CatalogueRecordLookupTool(config=catalogue_config)
    tools = ToolRegistry((literature_tool, catalogue_tool))
    agents = AgentRegistry(
        (
            LiteratureDefinitionAgent(),
            CatalogueDataAgent(available_fields=catalogue_tool.columns),
        )
    )
    return agents, tools


def build_specialist_layer(
    retriever: SearchRetriever,
    graph_driver: GraphDriver,
    *,
    literature_config: LiteratureSearchConfig | None = None,
    catalogue_config: CatalogueLookupConfig | None = None,
    graph_config: GraphInvestigationConfig | None = None,
) -> tuple[AgentRegistry, ToolRegistry]:
    """Register all four bounded specialists and their one-tool-per-agent interfaces.

    The Neo4j driver is injected by the caller and remains caller-owned. This assembly function
    does not open connections, route questions, or invoke agents. The existing two-specialist
    factory remains available so current tests and consumers retain their original behavior.
    """
    literature_tool = LiteratureSearchTool(retriever, config=literature_config)
    catalogue_tool = CatalogueRecordLookupTool(config=catalogue_config)
    graph_tool = GraphInvestigationTool(graph_driver, config=graph_config)
    quantitative_tool = QuantitativeCalculatorTool()
    tools = ToolRegistry(
        (literature_tool, catalogue_tool, graph_tool, quantitative_tool)
    )
    agents = AgentRegistry(
        (
            LiteratureDefinitionAgent(),
            CatalogueDataAgent(available_fields=catalogue_tool.columns),
            GraphInvestigationAgent(),
            QuantitativeAnalysisAgent(calculator_tool=quantitative_tool),
        )
    )
    return agents, tools
