# ExoTrace Investigation Planner and Orchestrator

## Scope of this milestone

This module adds a planning-and-investigation path alongside the existing direct answer CLI. It does not replace retrieval or answer generation, and it does not synthesize the final scientific answer. Its output is a structured, auditable bundle of specialist findings and source provenance.

## Runtime flow

1. `OpenAIResponsesTaskPlanner` receives the user's question plus the live agent and tool descriptors.
2. It makes one Responses API call and returns a structured plan. The list of allowed agent IDs is derived from the registry at runtime.
3. `InvestigationOrchestrator` checks each planned agent ID, requested capability, task-context schema, registered tool, and task budget.
4. The orchestrator assigns tool permissions from the chosen agent's declared allowlist. The model cannot grant an agent additional tools.
5. Registered specialists run in planned order. Each result is validated against its task and descriptor. One specialist failure is recorded and does not automatically prevent later tasks from running.
6. The report retains the plan, per-task findings, evidence objects, source URLs/record IDs/snapshot IDs, task errors, and timestamps.

The initial orchestration is a bounded single planning pass, not an unbounded autonomous loop. A question that needs clarification returns the questions without invoking any specialist. A plan can be reviewed with `--plan-only` before any specialist runs.

## Responsibilities remain separate

- The **planner** chooses specialist work based on live contracts; it does not gather evidence or author the scientific answer.
- The **Literature & Definition Agent** searches the configured references corpus and returns passages with provenance.
- The **Catalogue Data Agent** fetches requested source fields using explicit filters; it does not interpret values or calculate measurements.
- The **Graph Investigation Agent** executes named, read-only, parameterized graph operations; it does not interpret relationships scientifically.
- The **orchestrator** validates, delegates, aggregates and records. It does not route using question keywords.
- A separate **Answer Synthesis Agent** is intentionally not part of this milestone.

## Data-driven contracts and security

Each `AgentDescriptor` exposes its `task_context_schema`. The planner sees those schemas and the tool schemas. The catalogue agent schema gets its `fields` enum from the currently loaded, manifest-validated CSV column names. The graph operation enum comes from `GraphInvestigationTool.SUPPORTED_OPERATIONS`. No scientific definition or column glossary is embedded in the planner.

The orchestrator supports only the schema keywords currently used by ExoTrace task contracts and fails closed on unknown keywords. It validates contexts before specialist execution. Agent task tool permissions are assigned from the registered agent's descriptor, not accepted from model output. The existing `ToolRegistry` enforces the intersection of the agent and task tool allowlists.

Tools declare whether authentication is required. The CLI only prompts for a Neo4j password when a planned task selects a tool whose descriptor declares that requirement. Tool instances, API keys and passwords are not included in the planner's prompt.

## Environment configuration

The planner reuses the existing API key and model settings:

```dotenv
OPENAI_API_KEY=your_api_key_here
EXOTRACE_LLM_MODEL=your_available_model_id_here
```

Optional planner-specific settings:

```dotenv
EXOTRACE_PLANNER_MODEL=your_available_model_id_here
EXOTRACE_PLANNER_TIMEOUT_SECONDS=60
EXOTRACE_PLANNER_MAX_OUTPUT_TOKENS=1400
EXOTRACE_MAX_AGENT_TASKS=5
```

If `EXOTRACE_PLANNER_MODEL` is unset, the planner uses `EXOTRACE_LLM_MODEL`. The application intentionally does not hardcode a model ID. Do not share API keys in chat, code or logs.

For live graph tasks, configure the existing Neo4j values in `.env` when available:

```dotenv
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_local_neo4j_password
NEO4J_DATABASE=exotrace
```

Do not overwrite existing `.env` settings blindly. Add or update only the values that are missing.

## Run

Review a plan without invoking specialists:

```powershell
python -m exotrace.agents.investigate --query "What does planetary orbital eccentricity describe?" --plan-only --save-json data/manifests/plan_preview.json
```

Run the planned specialist tasks:

```powershell
python -m exotrace.agents.investigate --query "What does planetary orbital eccentricity describe?" --save-json data/manifests/investigation_report.json
```

Override the configured task budget for one run:

```powershell
python -m exotrace.agents.investigate --query "Compare the requested exoplanets" --max-agent-tasks 4
```

The report is deliberately not presented as a synthesized answer. The next milestone is the separate Answer Synthesis Agent that will convert validated specialist findings into a cited response.

## Offline validation

```powershell
python -m pytest tests/test_dynamic_planner.py tests/test_orchestrator.py -q
python -m pytest -q
```

The tests use an injected fake Responses transport and fake tools. No live OpenAI API call or Neo4j query is required to run the test suite. The CLI `--help` path was also tested locally. A real planner request and live Neo4j execution still require validation in the user's workspace.
