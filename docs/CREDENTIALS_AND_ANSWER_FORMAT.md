# ExoTrace credentials and answer presentation fix

## User-facing behaviour

- The Streamlit UI no longer asks for or accepts a Neo4j password.
- The investigator CLI and UI readiness checks continue to load the project's local `.env` via the existing `_load_local_settings` helper. If `NEO4J_PASSWORD` is absent, graph-only tasks are stopped with a clear message; catalogue and literature tasks remain usable.
- The UI does not pass a password override to child processes and removes legacy password-field state from the Streamlit session.
- Synthesized findings are grouped by their existing evidence ID tuple. Claims tied to the same catalogue record appear together and cite that record once per group.
- Partial results show a succinct notice that some work did not complete.
- For the `host_planets` graph operation, the specialist maps the generic `planet_name` input to the registered `host_name` parameter when the planner chooses the operation but emits the older/generic key. This is an operation-contract adapter only; it does not infer entities from natural-language keywords.

## If Neo4j credentials are missing

Set `NEO4J_PASSWORD` once in the local, gitignored project `.env` file alongside the existing Neo4j URI/username settings. Do not paste the secret into the chat or a report. The UI never displays or stores it. If the password is already present in the process environment, that value takes precedence.

## Files

- `src/exotrace/ui/app.py`
- `src/exotrace/ui/presentation.py`
- `src/exotrace/agents/graph_investigation.py`
- Regression tests under `tests/`
