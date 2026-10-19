# ExoTrace Frontend Runtime Fix

This focused patch fixes two issues observed after launching the simplified Streamlit interface.

## Changes

1. Removes the invalid text characters passed as Streamlit alert `icon` parameters. Streamlit validates alert icons as emoji; plain `✓` and `!` caused the app to crash. The alerts now use Streamlit's default icons.
2. Passes project-relative CLI paths using forward slashes (`Path.as_posix()`) for `--save-json`, `--plan-json`, and synthesis `--report` / `--save-json` arguments. Python's path handling on Windows accepts forward slashes, and this keeps command arguments portable and predictable.
3. Updates the path expectation in the UI service test to be platform independent.
4. Adds a regression test for invalid alert icon tokens.

## Validation

Offline full suite: 224 passed, 2 skipped. The skipped tests require the optional `langgraph` package, which is absent in the isolated validation environment. This does not validate the user's Windows browser session or live integrations.

## Scope

Only these files are replaced:
- `src/exotrace/ui/app.py`
- `src/exotrace/ui/service.py`
- `tests/test_ui_html_rendering.py`
- `tests/test_ui_service.py`

No `.env`, model configuration, source data, FAISS index, Neo4j database, planner, agents, or scientific tools are changed.
