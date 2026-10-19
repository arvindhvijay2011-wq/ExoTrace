# ExoTrace Hero UI Patch

## What changes

- Replaces the text-only opening block with a locally bundled, wide hero image based on the supplied 4K ExoTrace intro artwork.
- Keeps the three starter-question buttons and the existing primary question form beneath the hero.
- Adds a direct link to the NASA Exoplanet Archive and a short note that ExoTrace is an independent research interface.
- Keeps the existing single-question workflow, sidebar controls, investigation execution, answer rendering, evidence, and follow-up-removal changes intact.
- Uses a local asset so the hero does not depend on an external image host at runtime.

## NASA branding

The patch does not add the standard NASA insignia or say "Powered by NASA". NASA's current brand guidelines state that its insignia/logotype may not be used on third-party webpages without explicit permission and must not imply endorsement. The separate NASA Data Insignia also requires prior approval. ExoTrace therefore credits the NASA Exoplanet Archive as a data source and makes its independent status explicit. Sources: https://www.nasa.gov/nasa-brand-center/brand-guidelines/ and https://www.nasa.gov/nasa-data-insignia/.

## Files

- Replaces `src/exotrace/ui/app.py` only.
- Adds `src/exotrace/ui/assets/exotrace_intro_banner.jpg`.
- Adds `tests/test_exotrace_hero_ui.py` and this documentation.
- Does not modify planner, agents, tool schemas, validation, service execution, `.env`, catalogue, vector index, or Neo4j data.

## Verify

From the project root:

```powershell
python -m pytest tests/test_exotrace_hero_ui.py tests/test_single_question_ui_regression.py -q
python -m pytest -q
```
