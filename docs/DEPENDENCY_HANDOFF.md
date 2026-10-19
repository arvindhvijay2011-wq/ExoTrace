# ExoTrace dependency-aware evidence handoff

## Purpose

The planner can now express a directed task plan. Each task receives a unique `task_key` and a `depends_on` list containing only task keys that appear earlier in the plan. Independent tasks use an empty dependency list.

The orchestrator executes tasks in plan order. It passes a task only evidence newly produced by its declared dependencies, not every prior result in the investigation. This is a least-privilege data-flow rule: the agent's task schema and tool allowlist still determine what it may do, while dependency edges determine which upstream evidence it receives.

## Provenance metadata

Before newly produced evidence becomes available to downstream tasks, the orchestrator adds:

- `exotrace_producer_task_key`: the exact plan key that produced the evidence
- `exotrace_producer_agent_id`: the registered specialist identifier

Source ID, evidence ID, source URI, record ID, source snapshot, excerpt, and existing metadata are preserved. If multiple dependencies provide the same evidence ID with conflicting provenance, the orchestrator rejects the handoff rather than choosing arbitrarily.

Evidence passed through from a prior task is not treated as newly produced output of the forwarding task. This preserves provenance and avoids accidental duplicate or misleading dependency ownership.

## Quantitative source references

A quantitative task declares each operand symbolically in its own context:

```json
{
  "source_task_key": "measurement-a",
  "field": "pl_rade"
}
```

The `source_task_key` must name a declared dependency whose returned evidence is available to the task. The agent finds exactly one matching structured source record that contains the requested field. If the record is absent, the value is missing or nonnumeric, or multiple records match, calculation is refused. The planner never supplies the measured numeric value directly.

The selected raw value is sent to the deterministic calculator as its original decimal string. The calculator re-reads the same field from the cited evidence and compares the numeric values using `Decimal`, reducing the risk of binary floating-point rounding during handoff.

## Units and limitations

If source evidence contains a `declared_unit` metadata value, the agent carries that declared label forward. For current catalogue records that do not expose a normalized unit field, the agent uses an explicit opaque label of the form `source-native:<field>@<snapshot>`. That label identifies the source field and snapshot, not a verified physical unit. Unit conversion is not performed, and the synthesis layer must not silently reinterpret the token as a familiar unit such as Earth radii or kilometres.

Operations requiring matching units reject operands with different unit labels. Ratio and product operations preserve their dimensional labels according to the registered calculator operation. Because actual physical-unit normalization is not yet implemented, cross-field scientific calculations should be treated conservatively unless the source evidence supplies verified unit metadata.

## Runtime and safety boundaries

- No keyword-based question routing was added.
- Agent IDs, capabilities, operation IDs, and field names continue to come from live registries and source schemas.
- Every dependency must point to an earlier task; future, unknown, duplicate, or self-dependencies are rejected.
- A downstream task only sees declared dependency outputs.
- The quantitative agent has no retrieval or graph tool permission. Its only tool is the deterministic calculator.
- Existing direct-answer and synthesis entry points remain available.

## Validation

The added integration test uses deterministic test records to verify the complete flow: two source tasks return high-precision decimal strings, the orchestrator tags and hands off their evidence, and the quantitative agent calculates from those exact source values. A companion test verifies that evidence from an undeclared task is not accessible to the calculator task.
