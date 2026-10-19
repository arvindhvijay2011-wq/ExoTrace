# ExoTrace LangGraph Migration Patch Notes

This patch adds an optional LangGraph-backed workflow and a CLI selector. The legacy engine remains the default and the fallback.

## Added

- `src/exotrace/agents/langgraph_workflow.py`: lazy-imported `StateGraph` lifecycle; structured typed state; plan, conditional route, preview, and execution nodes.
- `requirements-langgraph.txt`: optional LangGraph v1.x dependency.
- `tests/test_langgraph_workflow.py`: offline branch and integration-adapter tests, plus a real LangGraph integration test that runs when the package is installed.
- `docs/LANGGRAPH_MIGRATION.md`: architecture, installation, smoke-test and migration scope.

## Replaced

- `src/exotrace/agents/investigate.py`: adds `--engine {legacy,langgraph}`. The default remains `legacy`.
- `src/exotrace/agents/__init__.py`: exposes LangGraph workflow classes using the existing lazy-export pattern.

## Important testing note

The build environment used to prepare this patch does not have network access to install LangGraph. The full suite passes with the offline graph test double; the real `StateGraph` integration test is skipped here and will run on your machine after `python -m pip install -r requirements-langgraph.txt`. Do not switch the default engine until that local test passes and representative legacy/LangGraph reports have been compared.
