# ExoTrace Streamlit Frontend Patch

## Adds

- `streamlit_app.py`: front-end launcher with source-path bootstrap.
- `src/exotrace/ui/app.py`: frosted-glass dark scientific workspace, plan review, results, evidence ledger, and history.
- `src/exotrace/ui/service.py`: safe `subprocess.run` bridge to the existing investigation and answer-synthesis CLIs. It passes the query as one argument, never invokes a shell, preserves the existing `.env`, and stores JSON reports under `data/manifests/ui_runs/`.
- `tests/test_ui_service.py`: offline tests for subprocess argument safety, reviewed-plan replay, local report storage, environment handling, and synthesis JSON validation.
- `docs/FRONTEND.md`: launch instructions and workflow notes.
- `requirements-ui.txt` for the optional Streamlit install. The patch intentionally leaves the existing `pyproject.toml` untouched.

## Run

```powershell
python -m streamlit run streamlit_app.py
```

The app always previews and displays a plan before the user can execute it. Execution passes the saved plan back to the existing CLI, which revalidates it. Final cited answer synthesis is a separate, optional API request.

## Test notes

The frontend service tests are offline and mock subprocess execution. In the assembled source tree used to validate this patch, the full available pytest suite completed with **209 passed and 2 skipped**. The two skipped tests require the optional `langgraph` package, which is unavailable in that isolated test environment. No live OpenAI API or user's Neo4j database was accessed during these tests.
