# ExoTrace: First Two Specialist Agents

## Design

These are bounded, deterministic specialist workers that implement the existing `SpecialistAgent` contract. They do not use LLM calls and do not route by question keywords. The future planner/orchestrator will delegate tasks to them using declared capabilities and structured context.

## 1. Literature & Definition Agent

Identifier: `literature_definition`

Responsibility: retrieve reference passages and source-derived parameter definitions, preserving source URIs, source document IDs, retrieval scores/ranks, and snapshot provenance when available.

Only permitted tool: `literature.search`.

The tool wraps the existing retriever instance passed at assembly time. It never creates a second FAISS index or embedding model. Its retrieval scope is deliberately locked to the existing `references` scope. Strategy/result limits are configurable through `LiteratureSearchConfig`, rather than switched by query shape.

Task contract:

```python
AgentTask(
    task_id="task-literature-001",
    question="What does the requested parameter describe?",
    objective="Find source passages that define the requested parameter.",
    required_capabilities=("parameter.definition",),
    allowed_tool_ids=("literature.search",),
    context={"search_query": "parameter name or requested definition", "top_k": 6},
)
```

`search_query` is an optional explicit override; absent it, the question is passed to retrieval unchanged. No keywords are inspected to select a retrieval strategy.

## 2. Catalogue Data Agent

Identifier: `catalogue_data`

Responsibility: retrieve raw catalogue field values from the validated PSCompPars snapshot and return them with source-row and snapshot provenance.

Only permitted tool: `catalogue.lookup`.

The tool verifies `data/processed/planets_validated.csv` against `data/manifests/validation_report.json` and derives the snapshot identifier from the manifest's raw SHA-256 using the same snapshot identity convention as the graph importer. It derives available fields from the CSV header instead of maintaining a hand-written parameter glossary. Cell values are preserved as strings so formatting is not silently normalized.

Task contract:

```python
AgentTask(
    task_id="task-catalogue-001",
    question="Retrieve the requested catalogue fields for the named record.",
    objective="Return exact raw values and provenance for the explicitly identified record.",
    required_capabilities=("catalogue.raw_values",),
    allowed_tool_ids=("catalogue.lookup",),
    context={
        "filters": {"pl_name": "an exact name from the caller"},
        "fields": ["pl_name", "hostname", "pl_orbper"],
        "match_mode": "exact",
        "limit": 10,
    },
)
```

Filters and fields are data supplied by the planner/caller. The agent does not infer them from the English question. `contains` matching is available only when explicitly requested. A result limit can return `partial` status and states how many records matched and were returned.

## Build and execute (programmatic integration)

The current direct CLI remains unchanged. A future orchestration entry point can assemble the specialists using the existing retriever:

```python
from exotrace.agents import build_initial_specialist_layer
from exotrace.agents.contracts import AgentTask
from exotrace.vector.retrieve import HybridTextRetriever

retriever = HybridTextRetriever(device="cpu")
agent_registry, tool_registry = build_initial_specialist_layer(retriever)

agent = agent_registry.get("literature_definition")
task = AgentTask(
    task_id="task-literature-001",
    question="What does planetary orbital eccentricity describe?",
    objective="Retrieve the relevant source definition.",
    required_capabilities=("parameter.definition",),
    allowed_tool_ids=("literature.search",),
)
executor = tool_registry.executor_for(agent.descriptor, task)
result = agent.run(task, tools=executor)
result.validate_for(task, agent.descriptor)
```

Catalogue tasks require structured `filters` and `fields` in `context`; an example is given above. The catalogue tool checks the project snapshot on construction, so its CSV and validation report must already exist.

## Boundaries and limitations

- Agents cannot use tools unless both their descriptor and the assigned task allow them.
- The literature agent receives no catalogue tool; the catalogue agent receives no literature tool.
- The catalogue adapter validates the processed file hash against the report before reading rows. If the CSV no longer matches the manifest, it stops rather than silently using changed values.
- The catalogue adapter does not query Neo4j. Its record IDs are derived using the project's snapshot and planet-name convention, permitting later graph integration while preserving source-row identity.
- These agents do not yet decide when to invoke one another. A separate orchestrator is a later milestone.
