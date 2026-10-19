# ExoTrace answer-first UI

## User-facing behavior

- The default flow is `Ask ExoTrace`: preview and validate the plan internally, execute only when the plan passes guards, then render the answer.
- Plan review is optional and defaults off. It can be enabled under Advanced settings for users who want to inspect task decomposition before execution.
- A plan that does not pass validation is not executed. The default interface presents a short, actionable message and hides planner internals in a disclosure.
- Deterministic calculation results are rendered directly from calculator evidence and the symbolic operands declared by the saved plan. The language model is not asked to restate a calculation result, preventing a second answer from accidentally reversing a numerator and denominator. If a quantitative task fails, the UI does not ask a language model to invent a substitute calculation.
- Explanatory questions are synthesized into a cited answer automatically. The user does not need to enable answer generation.
- Evidence, source records, snapshot identifiers, execution counts, raw JSON, and logs are available only in collapsed disclosure sections.
- Research history is available in a collapsed section at the bottom of the page.

## Scope

This is a frontend behavior change. It does not modify the planner, specialist agent implementations, catalogue retrieval, computation tools, environment settings, frozen dataset, FAISS index, or Neo4j database.
