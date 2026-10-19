# ExoTrace Graph Investigation Agent Patch

This is an additive third-specialist patch following the agent contracts and the Literature/Catalogue specialists.

## New code

- `src/exotrace/tools/graph_investigation.py`: parameterized, read-only operations over the existing graph schema.
- `src/exotrace/agents/graph_investigation.py`: a graph-only specialist with an explicit task and tool contract.
- `tests/test_graph_investigation_tool.py`: fake-driver tests for query parameters, provenance, errors, bounds, and rejection of arbitrary Cypher.
- `tests/test_graph_investigation_agent.py`: specialist responsibility, permission, no-keyword-routing, and assembly tests.
- `docs/GRAPH_INVESTIGATION_AGENT.md`: behavior, boundaries, and usage.

## Updated complete files

- `src/exotrace/agents/assembly.py`: keeps `build_initial_specialist_layer()` unchanged in behavior and adds `build_specialist_layer()` for all three specialists.
- `src/exotrace/agents/__init__.py`: lazy public export of the new specialist/factory.
- `src/exotrace/tools/__init__.py`: public exports for graph tool/config/protocol.

## Safety boundary

The LLM will not provide Cypher. The tool only executes named templates whose entity values are bound parameters. It uses Neo4j managed read transactions and returns source-record/snapshot provenance. It does not change the dataset, FAISS index, corpus, or graph.

## Applying the patch

The three files in the existing `agents`/`tools` package exports and `agents/assembly.py` intentionally replace older complete versions. Back them up before extraction.
