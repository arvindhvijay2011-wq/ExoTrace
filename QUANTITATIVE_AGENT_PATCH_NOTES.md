# ExoTrace Quantitative Agent + LangGraph Integration Patch

## What this adds

- A bounded Quantitative Analysis Agent registered in the investigation specialist layer.
- A deterministic calculator whose operation list and planner schema come from a runtime operation registry.
- Dependency-aware evidence handoff: the planner references source task keys and field names, never fabricated operand values.
- Exact source-field resolution from prerequisite evidence and Decimal-based validation/calculation.
- Rejection of missing, non-numeric, ambiguous, undeclared, mismatched-unit, or invalid-operation operands.
- Source, record, snapshot, field, and evidence-ID provenance for each derived result.
- Full updated planner/orchestrator/CLI/LangGraph files from the tested integration baseline, preserving dependency-aware task execution and checkpoint integration.
- Focused unit, handoff, planner, orchestrator, and LangGraph tests and documentation.

## Important unit limitation

For NASA catalogue fields that do not carry verified unit metadata in the evidence record, the agent uses an opaque `source-native:<field>@<snapshot>` label. This label is not a physical unit and must not be presented as Earth radii, kilometres, or another familiar unit without a separate source-backed unit-resolution step. The current calculator does not perform unit conversion.

## Files and settings

The patch does not include or modify `.env`, API keys, the local NASA CSV, Neo4j data, FAISS indexes, or other runtime data. It uses the existing ExoTrace settings and project configuration.

## Validation performed in the assembled source tree

`PYTHONPATH=src python -m pytest -o addopts='' -q -ra`

Result: **222 passed, 2 skipped**. Both skips are integration tests that require the optional `langgraph` package, which is not installed in this isolated test environment. The user's local `.venv` may include it; run the same test command there to exercise the real LangGraph integration.

This is test-suite validation against an assembled source copy, not a claim that the patch has been executed inside the user's Windows workspace or connected to their live Neo4j/database files.
