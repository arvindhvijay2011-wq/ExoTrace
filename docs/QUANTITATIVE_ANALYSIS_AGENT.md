# ExoTrace Quantitative Analysis Agent

## Responsibility

The Quantitative Analysis Agent performs explicit, deterministic calculations over numeric values
from structured evidence returned by declared prerequisite tasks. It does not retrieve records,
invent numeric measurements, interpret scientific meanings, convert units, or compose the final
answer. The production specialist assembly registers it alongside the Literature, Catalogue, and
Graph specialists, and exposes only the deterministic calculator tool to it.

A planned calculation references upstream task keys and source field names. The orchestrator
hands the quantitative task only fresh evidence produced by its declared dependencies. The agent
then resolves each operand to exactly one structured evidence record and field. The planner cannot
supply the operand's measured value directly.

## Generic arithmetic operations

The current operation registry provides `sum`, `difference`, `mean`, `ratio`, `percentage_change`,
and `product`. Operation definitions are held in a registry, and the agent's task schema derives
its operation enum from the live registry. These are generic mathematical operations, not
exoplanet-specific routing rules.

| Operation | Operand order | Unit behavior |
|---|---|---|
| `sum` | Two or more values | Requires identical unit labels; output retains that label. |
| `difference` | First minus second | Requires identical unit labels; output retains that label. |
| `mean` | Two or more values | Requires identical unit labels; output retains that label. |
| `ratio` | First divided by second | Identical labels cancel to `1`; otherwise a symbolic ratio label is returned. |
| `percentage_change` | Baseline, then comparison value | Requires identical labels and a nonzero baseline; output is `%`. Formula: `(comparison - baseline) / baseline * 100`. |
| `product` | Two or more values | Values are multiplied and non-dimensionless labels are joined symbolically. |

## Source-value verification and provenance

Before calculation, the agent:

1. verifies that each requested upstream task is a declared dependency and that its produced
evidence was handed off by the orchestrator;
2. resolves the requested field from the JSON record excerpt rather than accepting a free-form
numeric value from the planner;
3. rejects absent, nonnumeric, non-finite, or ambiguous source values;
4. passes the exact source value and evidence ID to the calculator, which independently checks the
value against the cited source record using `Decimal` arithmetic; and
5. retains input evidence and returns derived evidence containing the operation, value, operand
fields, source/evidence IDs, source units/labels, and snapshot provenance.

## Unit limitations

No unit conversion is performed, and unit labels are not independently validated for physical
meaning by the calculator. If source evidence declares a unit in its metadata, the agent preserves
that label. For catalogue fields without verified unit metadata, it uses an opaque label of the
form `source-native:<field>@<snapshot>`. This label identifies the field and frozen source snapshot;
it is **not** a physical unit. Do not present it as Earth radii, kilometres, or another familiar
unit without a separate source-backed unit-resolution step.

Operations requiring like units reject mismatched labels. Ratios of the same source field and
snapshot can cancel the opaque labels, but this does not validate cross-field unit compatibility.
For example, a meaningful comparison of two planets' radii can be expressed as a ratio only after
both radius operands have been retrieved from the frozen catalogue; a difference needs verified
physical-unit metadata before it can be rendered with a familiar unit label.

## Example structured task context

The calculation task references two prior lookup tasks and asks for a difference between a field
from each source record. It does not contain the values themselves:

```json
{
  "calculations": [
    {
      "calculation_id": "radius-difference",
      "operation": "difference",
      "operands": [
        {"source_task_key": "lookup-planet-a", "field": "pl_rade"},
        {"source_task_key": "lookup-planet-b", "field": "pl_rade"}
      ]
    }
  ]
}
```

The plan must also declare `lookup-planet-a` and `lookup-planet-b` as dependencies of the
calculation task. Each lookup must return exactly one matching record with the requested field.
If either source task fails, the field is absent or ambiguous, the value is nonnumeric, units are
incompatible for the requested operation, or an operation's mathematical preconditions fail, the
calculation is rejected instead of producing an unsupported result.

## Running tests

```powershell
python -m pytest tests/test_quantitative_calculator.py tests/test_quantitative_analysis_agent.py tests/test_quantitative_handoff.py -q
python -m pytest -o addopts='' -q -ra
```
