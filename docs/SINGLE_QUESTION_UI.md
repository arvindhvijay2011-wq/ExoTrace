# ExoTrace single-question UI patch

## Scope

This patch removes follow-up functionality from the Streamlit UI for now. It removes the follow-up form, the code that builds a follow-up planner prompt from the previous answer, the pending-follow-up submission path, and the now-unused planner-query session state. A prior version's leftover follow-up session keys are cleared on page startup.

The primary question form and the existing investigation pipeline continue to use the submitted question directly. No agent, planner, tool, schema, validation, catalogue, vector-index, Neo4j, credential, or synthesis contracts are changed.

## Sidebar

The sidebar is collapsed by default, but remains available from Streamlit's sidebar toggle. Its Advanced settings remain intact because they affect real runtime behavior:

- readiness/configuration indicators explain missing research assets or model configuration;
- plan review lets a researcher inspect the plan before executing specialists;
- maximum specialist tasks bounds the requested plan size;
- planner output budget controls token budget for the planner subprocess launched by the UI;
- CPU/CUDA selects embedding inference device.

## Files

- Replaces `src/exotrace/ui/app.py` only.
- Adds `tests/test_single_question_ui_regression.py`.
- Does not overwrite existing tests or application files other than `app.py`.

## Validation

The patch builder compiles the modified app file and its regression test. Run the new test and the full project test suite in the ExoTrace environment before relying on the change.
