# ExoTrace Graph Investigation Agent

## Scope

Adds one bounded specialist, `graph_investigation`, and one tool, `graph.investigate`. The agent retrieves graph relationships and their source provenance. It does not interpret scientific significance, retrieve text passages, fetch raw catalogue cell values, or calculate measurements.

## Fixed, read-only operations

The tool exposes three parameterized operations over the existing Neo4j import schema:

- `planet_context`: host-star edge, discovery method, discovery facility, discovery reference, and linked catalogue-record relationships for a named planet.
- `host_planets`: planets connected to a named host star through `HOSTS` relationships.
- `planet_records`: catalogue records linked to a named planet.

Only these operation names map to executable Cypher templates. User-controlled values are passed as parameters. Arbitrary Cypher, labels, relationship types, write statements, and dynamic query fragments are not accepted. Cypher runs via Neo4j managed read transactions (`execute_read`).

The fixed templates and operation names are intentional security boundaries. The returned scientific data, graph relationships, entity names, snapshot identifiers, and source record identifiers are read from Neo4j, not hardcoded in the agent.

## Inputs

Tasks supply explicit structured values through `AgentTask.context`:

- `operation`: one of the declared operation names.
- `planet_name`: required for `planet_context` or `planet_records`.
- `host_name`: required for `host_planets`.
- `result_limit`: optional and bounded by `GraphInvestigationConfig`.

The agent does not infer those values from the natural-language task question. The orchestrator that will later create these tasks is not part of this patch.

## Provenance and failure behavior

Each finding has an evidence ID connected to a `EvidenceReference` containing the graph relationship, source record ID, and snapshot ID. Rows without those provenance fields do not become factual findings; they make the result partial. Result caps are configurable. Database errors return structured failures without exposing the raw exception detail.

The tool takes an already-authenticated Neo4j driver by dependency injection. The driver remains owned by the caller; the patch does not change `.env`, open a database connection automatically, or run a live query during tests.

## Compatibility

`build_initial_specialist_layer()` continues to register only the original Literature and Catalogue agents. `build_specialist_layer(retriever, graph_driver, ...)` registers all three specialists. Neither factory runs an agent or routes a question.

## Tests

```powershell
python -m pytest tests/test_graph_investigation_tool.py tests/test_graph_investigation_agent.py -q
python -m pytest -q
```

All tests use fake Neo4j drivers and do not require a running Neo4j server.
