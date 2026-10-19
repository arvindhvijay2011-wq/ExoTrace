# ExoTrace First Two Specialist Agents Patch

This is the next additive step after the Agent Contracts and Tool Interfaces patch. It adds two narrow, read-only specialists and their concrete data adapters.

## Specialists included

### Literature & Definition Agent (`literature_definition`)

- Uses the existing `HybridTextRetriever` through an injected retriever interface.
- Can only invoke `literature.search`.
- Searches the configured `references` scope; this is a deliberate responsibility boundary.
- Uses the configured retrieval strategy and bounded result budget. These settings can be changed in `LiteratureSearchConfig`; query wording does not change the strategy or scope.
- Returns source excerpts and preserved provenance. It does not write a final answer, infer catalogue values, or calculate results.

### Catalogue Data Agent (`catalogue_data`)

- Uses `catalogue.lookup` to read the existing `data/processed/planets_validated.csv` snapshot.
- Requires a validation report and verifies the processed CSV SHA-256 before loading the snapshot.
- Uses field names from the actual CSV header; it contains no manually authored list of scientific parameters or definitions.
- Requires explicit structured `context.filters` and `context.fields`. It intentionally does not guess the target object or parse natural-language queries.
- Preserves raw cell strings, record ID, snapshot ID, source row number, checksum, and available per-field reference links.
- Does not write to CSV, FAISS, or Neo4j; does not calculate or interpret measurements.

## What this patch does not add

- It does not add an LLM planner/orchestrator. The future planner will decide which specialist to call and provide structured tasks.
- It does not add an LLM call inside either specialist. The specialists are deterministic, testable evidence workers, minimizing extra calls and leaving reasoning/synthesis to a later orchestration stage.
- It does not change the existing direct answer CLI, current vector retriever implementation, vector corpus, FAISS index, CSV files, Neo4j graph, or environment variables.
- It does not make claims that a source entails a conclusion; the specialists retrieve and preserve evidence for a later synthesis/audit stage.

## Source tree changes

Added:

- `src/exotrace/tools/literature_search.py`
- `src/exotrace/tools/catalogue_lookup.py`
- `src/exotrace/agents/_support.py`
- `src/exotrace/agents/literature_definition.py`
- `src/exotrace/agents/catalogue_data.py`
- `src/exotrace/agents/assembly.py`
- `tests/test_specialist_tools.py`
- `tests/test_specialist_agents.py`
- `docs/SPECIALIST_AGENTS.md`

Updated package exports, supplied as complete files:

- `src/exotrace/agents/__init__.py`
- `src/exotrace/tools/__init__.py`

The updated `__init__.py` files add exports for the new agents/configs/tools. Back them up before extraction as shown in the user instructions.

## Test commands

```powershell
python -m pytest tests/test_specialist_tools.py tests/test_specialist_agents.py -q
python -m pytest -q
```

Tests use fake retrieval results and temporary validated CSV files. They do not make network calls, invoke OpenAI, load the actual FAISS index, or connect to Neo4j.
