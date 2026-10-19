# ExoTrace agent and tool contracts

## Purpose of this patch

This is the first additive step toward ExoTrace's multi-agent architecture. It defines
stable data contracts, specialist/tool protocols, registries, and a least-privilege tool
executor. It does **not** implement an LLM planner or connect new agents to the current
retrieval/answering command yet. The existing application path is intentionally untouched.

## Contract boundaries

- `EvidenceReference` carries an investigation-local evidence ID alongside the native
  source ID and available source provenance.
- `Finding` carries one structured statement and the evidence IDs that support it. The
  contract does not invent source facts or impose a central list of finding categories.
- `AgentDescriptor` declares one implementation's name, responsibility, capabilities,
  and permitted tool IDs.
- `AgentTask` is a bounded work item containing a question, explicit objective, context,
  optional input evidence, constraints, and the tool IDs available for that task.
- `AgentResult` returns structured findings, new evidence, gaps, tool IDs used, and an
  outcome status. `validate_for` checks identity, tool permissions, and evidence references.
- `ToolDescriptor`, `ToolRequest`, and `ToolResult` define the transport contract for
  deterministic operations. Tools own the validation of their concrete arguments and
  output schema.

## Least privilege

An agent can call a tool only when that tool ID appears in **both** the agent descriptor's
`allowed_tool_ids` and the task's `allowed_tool_ids`. An empty task allowlist therefore
means no tools are available. The restricted executor verifies the response's tool and
call IDs against the request before returning it.

`read_only` is descriptive metadata, not an enforcement mechanism by itself. Concrete
implementations must still use read-only database credentials / read-only Cypher
operations and validate their inputs. The tool registry does not attempt to parse or
execute arbitrary Cypher or arbitrary Python.

## No question-specific routing

The registries do not route using words such as "eccentricity", "compare", or any other
question-specific terms. They expose the specialists' declared capabilities. A future
planner can select an investigation plan using those descriptions and the user's task,
then explicitly construct bounded `AgentTask` objects. Capability matching in
`AgentRegistry.candidates_for` is exact matching against declared capabilities, not an
implicit guess based on question text.

## Planned specialist boundaries

These are architectural responsibilities, not implemented agents in this patch:

1. **Investigation planner/orchestrator:** decomposes a question and delegates bounded
   work. It does not independently gather scientific evidence or author the final answer.
2. **Literature/definition specialist:** retrieves official source passages and parameter
   definitions through a retrieval tool.
3. **Catalogue-data specialist:** retrieves exact recorded values, units, uncertainties,
   and record provenance through validated catalogue queries.
4. **Graph-investigation specialist:** explores supported entity relationships through
   a restricted graph-query tool.
5. **Quantitative-analysis specialist:** runs deterministic, unit-aware calculations on
   validated inputs; it does not invent missing values.
6. **Answer-synthesis specialist:** combines returned findings and source references into
   a cited answer; it does not silently perform untracked research.
7. **Evidence-audit specialist:** conditionally examines claim-to-source support when
   the investigation merits another pass. It is not required for every simple definition.

The first three/four specialists should be implemented independently and tested before
an orchestrator is added. Each will receive only the tools appropriate to its explicit
contract. The direct-answer CLI and existing indexes remain the fallback and baseline.

## Intentional fixed rules

The fixed elements in this patch are protocol invariants and safety boundaries: unique IDs,
JSON-compatible payloads, evidence-reference validation, and tool access requiring both
allowlists to grant permission. Agent IDs, capability labels, tool IDs, scientific facts,
question-routing rules, and model identifiers are not centrally hardcoded here.
