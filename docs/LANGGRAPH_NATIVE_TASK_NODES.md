# ExoTrace: Native LangGraph Specialist Task Nodes

## Purpose

This migration moves individual planned specialist tasks into a plan-specific LangGraph execution
subgraph. The previous LangGraph phase wrapped the complete specialist execution loop in one node;
that loop is now represented by native nodes and dependency edges.

## Workflow shape

1. The outer LangGraph graph creates or accepts one validated investigation plan.
2. A plan-only run produces a preview without executing specialists.
3. A ready execution plan is validated against the live agent/tool registry and the current task
   budget before a task graph is compiled.
4. Each planned task gets one native `StateGraph` node. Node names are generated from task order;
   the actual task key, agent identity, context, capabilities, and dependencies come from the plan.
5. Tasks with no dependencies are graph roots. A task with one prerequisite has an ordinary edge;
   a task with multiple prerequisites has a multi-source join edge and waits for every prerequisite.
6. Terminal task nodes join at a finalizer that reconstructs results in original plan order.

Independent tasks can execute in the same LangGraph superstep. The two reducer-backed state maps
merge their disjoint per-task updates: one stores `AgentResult` records and the other stores only
newly produced `EvidenceReference` records. Duplicate task-key writes fail closed.

## Security and evidence contracts

The native task node calls `InvestigationOrchestrator.execute_planned_task`. The legacy engine calls
the same method, avoiding duplicate implementations of:

- plan/agent/tool/context validation;
- least-privilege tool execution through the existing restricted tool executor;
- dependency-only evidence handoff;
- result identity and evidence-reference validation;
- producer-agent/task provenance tagging;
- structured failure reporting.

The orchestrator checks dependency result status before execution. Downstream tasks do not run if
a required prerequisite failed or returned insufficient evidence. Only evidence produced by explicitly
declared dependencies is supplied to a task. Other nodes' output is not automatically exposed to it.

The planner still cannot execute tools directly. A graph is built only after the whole plan passes
current contract validation. Clarification/unsupported plans authorize no task nodes.

## Compatibility

The legacy engine remains available through `--engine legacy` and remains the default. The native
LangGraph path is opt-in with `--engine langgraph`. The plan-only and saved-plan flows remain
available; saved plans are revalidated against current registrations before execution.

No source catalogue, CSV, manifest, FAISS index, vector corpus, or Neo4j data is modified by this
patch. The Answer Synthesis Agent remains a separate command and has not been embedded into this
task execution graph in this phase.

## Validation

Offline tests use a deterministic StateGraph test double so dependency fan-in, state merging,
ordering, plan reuse, permissions at the orchestrator boundary, and failure-withholding paths can
be checked without network calls. When the optional LangGraph package is installed, an additional
integration test uses its real `StateGraph` API. That test must be run in the local `.venv` after
installing `requirements-langgraph.txt`; it is skipped in environments without LangGraph.
