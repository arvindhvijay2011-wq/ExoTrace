# ExoTrace frontend UI simplification patch

This patch reduces visible interface complexity without removing scientific traceability.

Expected experience:

1. A compact research workspace with one primary question input.
2. Short starter prompts, including an explicit numerator/denominator in the Kepler-10 comparison prompt.
3. A compact task-plan preview with technical context collapsed by default.
4. A calculation card that shows the numeric result and formula order derived from the saved plan.
5. Answers first; citations, evidence records, specialist outcomes, raw JSON, and CLI logs remain available on demand.
6. Advanced model and embedding controls remain accessible but are collapsed by default.

Files replaced/added: `src/exotrace/ui/app.py`, `src/exotrace/ui/presentation.py`, `tests/test_ui_presentation.py`, `tests/test_ui_html_rendering.py`.

No backend agents or source data are replaced by this patch.
