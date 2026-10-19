# ExoTrace saved-plan execution

## Why this exists

A `--plan-only` invocation and a later execution invocation are separate planner requests unless the saved plan is explicitly loaded. Because the planner is an LLM, two independent requests can return different plans. The `--plan-json` option lets the user execute the exact plan reviewed during preview.

## Recommended use

First create a plan preview:

```powershell
python -m exotrace.agents.investigate --engine langgraph --query "What does planetary orbital eccentricity describe?" --plan-only --save-json data/manifests/langgraph_plan_preview.json
```

Then execute the saved plan without asking the planner to choose again:

```powershell
python -m exotrace.agents.investigate --engine langgraph --query "What does planetary orbital eccentricity describe?" --plan-json data/manifests/langgraph_plan_preview.json --save-json data/manifests/langgraph_investigation.json
```

The supplied `--query` must match the saved report question after trimming surrounding whitespace. `--plan-json` cannot be combined with `--plan-only`.

## Validation and safety

The loader accepts only a JSON report whose status is `planned`, whose results array is empty, and whose plan disposition is `ready`. It rejects malformed tasks, unexpected task keys, question mismatches, and reports that represent clarification, unsupported work, or prior execution.

The loaded plan is not trusted merely because it came from a file. Before any specialist executes, the existing orchestrator revalidates it against the current agent registry, capabilities, context schemas, registered tools, permissions, dependencies, and configured task budget. Plans created under an older contract can therefore be rejected, and a fresh preview should then be generated.

The loader does not invoke the LLM planner. The CLI still loads the current application configuration and creates the specialist/tool layer needed to execute the plan.
