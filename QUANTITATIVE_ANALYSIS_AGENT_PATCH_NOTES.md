# ExoTrace Quantitative Analysis Agent Patch

This additive patch introduces one bounded specialist and its deterministic calculator tool.

## Included files

- `src/exotrace/tools/quantitative_calculator.py`
- `src/exotrace/agents/quantitative_analysis.py`
- `src/exotrace/agents/quantitative_assembly.py`
- `src/exotrace/tools/__init__.py` (complete updated file)
- `src/exotrace/agents/__init__.py` (complete updated file)
- `tests/test_quantitative_calculator.py`
- `tests/test_quantitative_analysis_agent.py`
- `docs/QUANTITATIVE_ANALYSIS_AGENT.md`

## Design boundaries

- No exoplanet-specific field names, scientific definitions, or question-keyword routing rules are embedded in the implementation.
- Calculation types are ordinary deterministic mathematical primitives registered through `CalculationOperationRegistry`; custom operations can be added without changing the agent.
- Each operand must map to a source field in a supplied `EvidenceReference` and its numeric value must equal the value encoded in that record.
- The tool does not perform unit conversion. Exact unit-label compatibility is checked for operations that require it. The caller remains responsible for sourcing the unit label.
- Failed/invalid calculation requests return no derived evidence.
- The existing default `build_specialist_layer()` is intentionally unchanged. The current planner/orchestrator cannot hand earlier task evidence to downstream tasks, so the quantitative specialist stays in a standalone registry until generic evidence handoff is implemented.
- No dependency additions, FAISS rebuilds, CSV changes, or Neo4j changes are required.

## Validation in the assembled project copy

- 26 tests added/updated for this patch passed in focused validation.
- Complete assembled project suite: 182 tests passed.
- Python compilation and import/export smoke checks passed.

These results are from the isolated environment available during patch construction. Run the tests in the actual Windows workspace after extraction.
