# ExoTrace Answer Synthesis Agent

## Responsibility

The Answer Synthesis Agent has one responsibility: convert a completed investigation report's
source evidence into a concise answer with claim-level citations. It has no retrieval or database
tools, does not select agents, does not calculate measurements, and does not perform a mandatory
second verification-model call.

## Execution

After running an investigation and saving its report:

```powershell
python -m exotrace.agents.synthesis --report data/manifests/investigation_report.json --save-json data/manifests/synthesized_answer.json
```

The synthesis CLI is separate from `exotrace.agents.investigate`; this keeps the working
investigation path unchanged while answer synthesis is tested independently.

## Evidence handling

The agent reads only `results[*].evidence` from the saved report. Each item is validated as an
`EvidenceReference`, duplicate evidence IDs are collapsed only when their source identity,
content, URL, snapshot, and record identity agree, and conflicting reuse of an evidence ID is
rejected. Source URLs, source record identifiers, and snapshot IDs are carried to the answerer.
The existing grounded answer component assigns short local citation IDs and validates that each
model-generated citation exists in the current evidence package.

## Model calls and limitations

With usable evidence, synthesis makes one configured Responses API request. With no usable
source evidence, the existing answer component abstains without a model request. This component
is not a semantic proof system: a model can still misjudge relevance or entailment. No optional
second-call citation verifier runs by default.

The agent uses the configured `OPENAI_API_KEY` and `EXOTRACE_LLM_MODEL`; no model ID is embedded
in this implementation. It does not modify the original investigation JSON.
