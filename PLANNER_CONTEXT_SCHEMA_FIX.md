# ExoTrace Planner Context Schema Fix

## Problem

The planner previously represented each specialist's context as `context_json`, a string that was expected to contain another serialized JSON object. Structured Outputs could guarantee that the field was a string, but not that the string itself was valid JSON. This caused errors such as:

`Planned task 1 context_json is not valid JSON.`

## Fix

- The planning response now represents each `context` as a real JSON object.
- Its strict response schema contains one task branch per currently registered specialist; each branch binds the agent ID to that specialist's current context schema.
- Optional fields are made nullable only for the strict API schema, then null placeholders are removed according to the original context contract.
- The catalogue specialist exposes its filter properties using the current validated CSV column list when created by the normal assembly layer. No catalogue field names are hardcoded.
- The original orchestrator context validation remains the enforcement boundary before any task executes.

## Complete files in this patch

- `src/exotrace/agents/planning.py` (complete replacement)
- `src/exotrace/agents/catalogue_data.py` (complete replacement)
- `tests/test_dynamic_planner.py` (complete replacement)

No indexes, datasets, manifests, Neo4j data, `.env`, or direct-answer CLI files are changed.

## Validation performed

In the assembled test project:

- Planner and orchestrator tests passed.
- Full suite: **147 passed**.
- `compileall` passed.
- `python -m exotrace.agents.investigate --help` passed.

The live Responses API request has not been tested from the user's Windows environment. Please rerun `--plan-only` after applying the patch.
