# ExoTrace Answer-First UI Patch

Replaces the Streamlit UI and UI calculation-presentation helper, and updates regression tests.

Default flow: ask a question -> internal plan validation -> investigation execution -> answer. Plan review is an opt-in setting.

Numerical responses use deterministic calculation evidence directly and do not run a separate LLM synthesis request for the same calculated answer. If a declared quantitative task fails, the UI will not ask the LLM to fill in or invent the missing calculation. Explanatory questions receive a cited answer automatically.

Tests run in the assembled local source tree: 229 passed, 2 skipped. The skipped tests require the optional `langgraph` package, which is not installed in this isolated test environment.
