# ExoTrace UI simplification

## Design goals

- Make the research question and answer the primary focus.
- Keep routine workspace status visible but move tuning controls into a collapsed Advanced settings section.
- Present the plan as a short task list. Put detailed task contexts behind expandable controls.
- Lead quantitative answers with the deterministic result and a formula derived from the saved plan's `source_task_key` and `field` operand references.
- Keep citation details, specialist traces, raw report JSON, and CLI logs available without forcing them into the main reading flow.

## Implementation

- `src/exotrace/ui/app.py`: updated Streamlit presentation and state flow.
- `src/exotrace/ui/presentation.py`: pure helpers to associate quantitative findings with the declared operation and symbolic operands.
- `tests/test_ui_presentation.py`: tests ratio order, source field labels, numeric formatting, and missing calculations.
- `tests/test_ui_html_rendering.py`: source-level tests for HTML rendering conventions.

The presentation code does not recalculate scientific values. The quantitative agent remains the authority for the result; this layer formats the returned value and displays the symbolic operands from the saved plan. The default Kepler-10 starter query explicitly requests `Kepler-10 c pl_rade / Kepler-10 b pl_rade`, but the displayed formula is always derived from the plan rather than hardcoded to those planets.

## Test

From the project root, run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_ui_presentation.py tests/test_ui_html_rendering.py tests/test_ui_service.py -q
```

Then launch:

```powershell
python -m streamlit run streamlit_app.py
```

The patch does not change orchestration, catalogue retrieval, calculator code, planner logic, environment settings, datasets, the FAISS index, or Neo4j.
