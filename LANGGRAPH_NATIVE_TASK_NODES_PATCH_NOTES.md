# ExoTrace Native LangGraph Task Nodes Patch

## Files in this additive migration

- `src/exotrace/agents/langgraph_workflow.py` — complete workflow rewrite; creates a native node per planned task.
- `src/exotrace/agents/orchestrator.py` — complete updated orchestrator with a shared single-task boundary, task-result finalizer, and prerequisite status checks.
- `tests/test_langgraph_workflow.py` — complete workflow test rewrite for DAG execution, joins, evidence handoff, saved-plan reuse, and no-task clarification.
- `tests/test_orchestrator.py` — complete test file with a regression test ensuring failed prerequisites withhold dependent specialist execution.
- `docs/LANGGRAPH_NATIVE_TASK_NODES.md` — architecture and safety notes.

## What changed

LangGraph no longer delegates a whole ready plan to `InvestigationOrchestrator.execute_plan`. It builds a subgraph with one native graph node per planned task and edges from declared dependencies. Multi-prerequisite dependencies use LangGraph's multi-source barrier edge. Independent roots can run in parallel and state reducers merge uniquely keyed results and freshly produced evidence.

The legacy orchestrator path uses the exact same `execute_planned_task` method for each sequential task. Permissions, context validation, result validation, evidence tagging, and dependency output selection stay centralized.

The planner, specialist implementations, synthesis CLI, retrieval/index files, catalogue data, and Neo4j database are not modified by this patch.

## Verification performed in the assembled test environment

- Full suite: 207 tests collected; 206 passed and 1 skipped.
- Compilation: passed.
- CLI help check: passed.
- The skipped test uses the real LangGraph package and must be run in the user's `.venv` after installing the optional dependency.
