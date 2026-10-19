# ExoTrace dependency handoff and quantitative planner integration

This patch connects the already-built Quantitative Analysis Agent to the default specialist registry through a generic dependency mechanism.

## Changes

- Planner task contracts include a unique `task_key` and an ordered `depends_on` list.
- Plans reject duplicate task keys and dependencies that do not reference an earlier task.
- The orchestrator passes only fresh evidence produced by explicitly declared dependencies and tags it with producer task and agent provenance.
- The quantitative agent now names upstream task keys and source field names instead of supplying numeric values itself.
- Source values are resolved from structured evidence at runtime and verified again by the calculator.
- The calculator preserves decimal strings through Decimal validation to avoid rounding source values into floats before calculation.
- The standard specialist assembly exposes the quantitative agent and calculator to the dynamic planner.
- The report renderer prints task keys and dependency edges.

## Validation performed in the assembled copy

- Full test suite passed.
- `compileall` passed.
- `python -m exotrace.agents.investigate --help` passed.
- Added end-to-end test confirms the orchestrator -> source tasks -> evidence handoff -> quantitative agent -> deterministic calculator path.

A live OpenAI planner call and live Neo4j/database query have not been tested by this offline patch run. The user's local workspace must rerun its tests and a plan-only investigation after installation.

## Units limitation

The current catalogue evidence format does not normalize physical units for every field. The agent uses any unit label included in source evidence; otherwise it uses an opaque source-native field/snapshot label. This does not claim to be a physically verified unit, and no conversion table or exoplanet-specific unit mapping is hardcoded.
