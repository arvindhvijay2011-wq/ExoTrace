# Planner completeness and dependency guidance

## Why this patch exists

A plan preview can be syntactically valid yet semantically incomplete. In particular, a summary can claim several stages while the executable `tasks` array contains only one stage. ExoTrace must treat the task array as the authoritative execution plan and inspect it before allowing execution.

## What changes

This patch strengthens the general system instructions sent to the registered-capability planner. They now explicitly require it to:

- represent every requested deliverable and prerequisite in the task graph;
- create upstream retrieval tasks for independently identified source records when a calculation depends on those values;
- create a distinct calculation task depending on all operand-producing tasks;
- refer to upstream task keys and fields rather than inventing numeric measurements;
- keep record-selection predicates separate from requested output fields where the agent schema distinguishes them;
- avoid asking users to repeat identifiers or snapshot names already supplied; and
- ensure the explanatory plan summary does not claim work missing from the actual tasks array.

The patch does not add query-specific routing, planet names, domain facts, source values, or new dependencies. Runtime agent registries and task-context schemas remain authoritative.

## Validation

The full available test suite in the assembled source tree passed with this patch, including a regression test that confirms the planner completeness instructions remain present. This checks the local implementation and planner request construction; it does not prove that every live model-generated plan will be complete. Continue inspecting a preview's actual task array before execution.
