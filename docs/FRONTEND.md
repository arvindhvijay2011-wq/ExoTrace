# ExoTrace Streamlit frontend

## Start the app

From the ExoTrace project root, with the existing virtual environment activated:

```powershell
python -m streamlit run streamlit_app.py
```

If Streamlit is not installed in that environment, install the optional UI dependency:

```powershell
python -m pip install -r requirements-ui.txt
```

The patch intentionally does not replace your existing `pyproject.toml`.

## Workflow

1. Enter a scientific question or choose one of the starter prompts.
2. Select **Review investigation plan**. ExoTrace calls the existing investigation CLI in plan-only mode and stores the validated-shape JSON report under `data/manifests/ui_runs/`.
3. Inspect the specialist tasks, required capabilities, dependency edges, and task contexts.
4. Select **Execute reviewed plan** to pass that exact saved plan back to the CLI. The CLI revalidates the plan and executes it through LangGraph.
5. Inspect specialist outcomes and the evidence ledger. Completed result reports remain available in local history.

The UI never implements planner routing or scientific calculations itself. It calls the same `exotrace.agents.investigate` CLI that has already been tested in the terminal. Reports and source provenance remain in JSON format for later inspection.

## Configuration and security

- API and Neo4j settings are read through ExoTrace's existing environment and `.env` conventions. The frontend does not show or save API keys.
- If a graph investigation needs Neo4j authentication and no password is present in the existing configuration, the sidebar offers a password input. The password is passed through the child process environment only, never written into investigation reports, and is not added to `.env`.
- The planner output-token budget is set for child processes launched by the UI; changing the slider does not modify `.env`.
- Each preview/result is stored under `data/manifests/ui_runs/`. The directory is excluded from version control by the patch's `.gitignore` update.
- The first UI intentionally uses an explicit preview-then-execute interaction. It does not automatically execute a plan immediately after generation.

## Limitations in this initial frontend

- The page displays a spinner during a backend run rather than streaming per-node LangGraph events. Once finished, it shows each specialist's status, findings, evidence, and provenance.
- Final answer synthesis is an additional API request and can be disabled with the sidebar checkbox. The specialist investigation report is saved even if synthesis fails.
- Streamlit session state holds the currently reviewed plan; the JSON report is the durable local artifact. Reloading the browser does not preserve unsaved session state, but saved executions remain in History.
- The application assumes the local frozen corpus, FAISS index, and any required Neo4j database are already prepared and running.
