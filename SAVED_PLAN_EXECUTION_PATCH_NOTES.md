# ExoTrace Saved Plan Execution Fix

This patch adds `--plan-json` to `python -m exotrace.agents.investigate` and introduces a strict saved-plan loader.

## Files

- `src/exotrace/agents/plan_io.py` (new)
- `src/exotrace/agents/investigate.py` (complete replacement)
- `tests/test_plan_io.py` (new)
- `docs/SAVED_PLAN_EXECUTION.md` (new)

## Local checks run

- Full assembled suite: 203 passed, 1 skipped.
- `compileall` passed.
- `python -m exotrace.agents.investigate --help` passed.

The skipped test is the optional real-LangGraph integration test in the environment where the dependency was unavailable. The patch is not a claim that a live OpenAI or Neo4j call was tested here.
