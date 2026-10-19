# ExoTrace frontend pipeline validation

## Why the failed investigation was incorrect

The previous planner-facing catalogue filter schema declared a mapping with every source column as a possible property. Strict structured output requires all properties in an object to be present, so the planner sometimes emitted unused fields as the literal string `"null"`. Those strings were treated as real catalogue predicates. In addition, the plan shown in the saved report omitted one explicitly named planet and the downstream calculation task, yet the UI's readiness check accepted any non-empty task array.

## Changes

- Catalogue filter input to the planner is now a compact list of `{ "field": ..., "value": ... }` clauses; this avoids emitting a placeholder for every possible source field.
- `CatalogueDataAgent` normalizes compact clauses to the lookup tool's mapping format, continues to accept mapping contexts for direct/legacy callers, and rejects placeholder values before tool execution.
- Planner instructions require minimal, user-grounded filter predicates and prohibit deriving catalogue constraints from fragments of an identifier.
- `plan_guard.py` checks plans against exact planet identifiers in the local validated catalogue. When a question names multiple exact catalogue planets and asks for arithmetic, it checks that the plan includes lookup tasks for each identifier and a quantitative task whose operands and dependencies reference those lookups.
- The Streamlit UI blocks plans that fail this guard and explains why. `execute_investigation` repeats validation before launching the CLI, so the disabled button is not the only protection.
- The result view no longer displays the misleading “plan is not executable” warning after a plan has already been executed.

## Apply and launch

Run `Apply_ExoTrace_Frontend_Pipeline_Guard_Patch.ps1` after downloading the ZIP and installer into the Downloads folder. The patch only replaces listed Python source, test, and documentation files; it does not modify `.env`, API keys, the dataset, FAISS files, Neo4j files, `pyproject.toml`, or `.gitignore`.

Restart Streamlit and click **Review investigation plan** again. Do not execute old saved previews that were made using the old mapping-shaped filter schema. The preview must show separate lookups for each named planet and a downstream calculation, and it must pass the pre-execution guard.

## Verification

The assembled offline test suite passed: 218 passed, 2 skipped. The skips are existing LangGraph integration tests whose optional dependency is not installed in this isolated validation environment. No live user workspace, browser, OpenAI API, or Neo4j database was exercised by these tests.
