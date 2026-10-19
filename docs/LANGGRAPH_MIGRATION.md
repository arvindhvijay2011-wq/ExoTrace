# ExoTrace LangGraph Migration: Phase 1

## Goal

Introduce LangGraph as an optional workflow engine without changing the existing specialist implementations, their tool permissions, the current planner contracts, or the default CLI engine.

## What LangGraph owns in this phase

The `langgraph` engine expresses this explicit state graph:

```text
START -> create_plan -> route_after_planning
                         |              |
                       preview        execute
                         |              |
                        END            END
```

- `create_plan` either asks the registered planner for a plan or accepts an already reviewed plan passed to `execute_plan`.
- The conditional edge selects `preview_plan` for `--plan-only` and `execute_plan` otherwise.
- Preview reports preserve `planned`, `needs_clarification`, or `unsupported` status without executing any specialist.
- The execute node passes a plan to `InvestigationOrchestrator.execute_plan`, which revalidates the plan and retains the tested least-privilege tool checks and provenance-aware dependency handoff.

This is a deliberate first migration step. The specialist-level dependency scheduler remains in the existing orchestrator for now. A later phase can move each task into native LangGraph nodes once this engine has passed local comparisons. No parallel custom copy of specialist permissions or evidence tagging has been introduced.

## Compatibility and defaults

- `--engine legacy` remains the default. Existing commands continue using the current orchestrator.
- `--engine langgraph` opts in to the new `StateGraph` lifecycle.
- `langgraph` is imported lazily. Users who do not install the optional dependency can continue using the legacy engine.
- This graph is stateless between invocations. Checkpoint persistence and resumable execution are deliberately deferred until the basic workflow has been validated.
- No question-keyword routing rules or scientific facts are introduced.

## Installation

Activate the project virtual environment, then run:

```powershell
python -m pip install -r requirements-langgraph.txt
```

The optional requirement is bounded to LangGraph v1.x. When adding the dependency to the project's package extras later, preserve the other existing `pyproject.toml` extras rather than replacing the file wholesale.

## Validation

Run the new workflow tests and then the whole project suite:

```powershell
python -m pytest tests/test_langgraph_workflow.py -q
python -m pytest -q
```

If LangGraph is installed, `test_real_langgraph_integration_when_dependency_is_installed` exercises the actual `StateGraph` API. Offline unit tests use a small test double to verify branch logic; they are not a substitute for that live integration test.

## Plan-only smoke test

```powershell
python -m exotrace.agents.investigate --engine langgraph --query "What does planetary orbital eccentricity describe?" --plan-only --save-json data/manifests/langgraph_plan_preview.json
```

Inspect the plan and verify that `planned`, `needs_clarification`, and `unsupported` routes produce no specialist execution.

## Execute smoke test

```powershell
python -m exotrace.agents.investigate --engine langgraph --query "What does planetary orbital eccentricity describe?" --save-json data/manifests/langgraph_investigation.json
```

Compare the report with the legacy engine for the same query. The content should be comparable because both engines currently use the same planner and `InvestigationOrchestrator` execution/validation path.

## Limits of Phase 1

- LangGraph owns lifecycle state and the plan/preview/execute conditional path.
- Per-specialist dependency scheduling is still handled inside `InvestigationOrchestrator`.
- No checkpoint saver, streaming, parallel execution, or automatic retry is enabled.
- The final answer synthesis remains a separate command/agent, as before.
