# ExoTrace Orchestrator Patch Notes

This patch adds a dynamic planner and bounded specialist orchestrator around the existing three specialists. It does not change the existing direct-answer CLI or rebuild any data artifacts.

## Added files

- `src/exotrace/agents/planning.py`
- `src/exotrace/agents/orchestrator.py`
- `src/exotrace/agents/investigate.py`
- `tests/test_dynamic_planner.py`
- `tests/test_orchestrator.py`
- `docs/INVESTIGATION_ORCHESTRATOR.md`

## Complete replacement files included in this patch

- `src/exotrace/agents/contracts.py`
- `src/exotrace/agents/catalogue_data.py`
- `src/exotrace/agents/graph_investigation.py`
- `src/exotrace/agents/assembly.py`
- `src/exotrace/agents/__init__.py`
- `src/exotrace/tools/contracts.py`
- `src/exotrace/tools/graph_investigation.py`
- `src/exotrace/tools/catalogue_lookup.py`

The changes add declared per-agent task-context schemas, source-derived field enums, registry-driven planning, a general tool authentication marker, and the command-line entry point. Existing agent/tool responsibilities remain narrow.

## Validation performed in the assembled test project

- `PYTHONPATH=src python -m pytest --override-ini addopts='' -q`: **146 passed**
- `PYTHONPATH=src python -m compileall -q src/exotrace`: passed
- `PYTHONPATH=src python -m exotrace.agents.investigate --help`: passed

These are isolated local tests. The real Responses API call and live Neo4j queries have not been performed in the user's Windows environment.
