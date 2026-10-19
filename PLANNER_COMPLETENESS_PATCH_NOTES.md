# ExoTrace Planner Completeness Fix

Files replaced:
- `src/exotrace/agents/planning.py`
- `tests/test_dynamic_planner.py`

New documentation:
- `docs/PLANNER_COMPLETENESS.md`

The change strengthens generic task decomposition, source-dependency, filter-vs-return-field, and summary-vs-task consistency instructions. It does not alter `.env`, API credentials, the frozen NASA files, the vector index, or Neo4j data.

Offline test result in the assembled source tree: **191 passed**.
