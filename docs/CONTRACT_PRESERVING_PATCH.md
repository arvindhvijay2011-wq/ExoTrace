# ExoTrace Conversational Answer Patch (Contract-Preserving)

This patch improves the existing answer-first Streamlit presentation and adds a small, source-derived default for broad catalogue requests. It is intentionally based on the previously supplied `catalogue_data.py` and `planning.py` files.

## Contract-preserving backend changes

- Keeps the catalogue planner's compact list of `{"field", "value"}` filter clauses.
- Keeps `_normalize_filters`, including legacy mapping support, duplicate-field detection, and rejection of null-like placeholder values.
- Makes only the `fields` context property optional. If it is omitted and the validated live source fields are available, the agent selects those fields. An explicitly empty or invalid field list still fails validation.
- Adds source-selection and broad-field guidance to the existing planner prompt while preserving the existing plan-completeness, dependency, entity-filtering, and placeholder safeguards.
- Does not modify orchestrator contracts, specialist permissions, tool contracts, retrieval contracts, credentials, or frozen data.

## UI changes

- Shows grouped, readable answer claims first.
- Moves source excerpts, links, record IDs, snapshots, and raw evidence identifiers behind expandable provenance details.
- Keeps the existing investigation/audit data available.

## Installation

Run the supplied PowerShell installer after downloading the ZIP to your Downloads folder. The installer backs up every replaced source file. The regression test is **additive** and uses a new filename; it does not overwrite any existing tests.

## Validation

From the project root:

```powershell
python -m pytest tests/test_conversational_defaults_regression.py -q
python -m pytest -q
```

The full suite should be run in the project's own environment before relying on the update. No live OpenAI, Neo4j, or Hugging Face request is made by the regression tests.
