# ExoTrace Windows Unicode CLI output fix

## Symptom

On Windows, some questions caused the Streamlit UI to show `ExoTrace CLI exited with code 1` with a diagnostic similar to:

`'charmap' codec can't encode character '\ufb03'`

The issue occurs when the child Python CLI prints output containing a Unicode character that is not representable in the active Windows locale code page. The UI subprocess bridge already captures and decodes child output as UTF-8, but the child process was not instructed to encode its standard streams as UTF-8.

## Change

The patch changes only `src/exotrace/ui/service.py`. In `_make_environment`, after approved per-child environment overrides are applied, it sets `PYTHONIOENCODING=utf-8` for the child Python process. This aligns the child's stdout/stderr encoding with the `encoding="utf-8"` used by `subprocess.run`.

This is local to ExoTrace child processes launched by the Streamlit UI. It does not change the parent Streamlit process environment, scientific logic, planner instructions, schemas, agent/tool permissions, catalogue filters, evidence checks, output report schema, or data files.

## Regression test

`tests/test_ui_unicode_stdio_regression.py` forces a legacy encoding in the parent environment and starts a child Python process which prints U+FB03 (`ﬃ`). It asserts the character survives UTF-8 capture without a child-process encoding error.

Run from the ExoTrace project root:

```powershell
python -m pytest tests/test_ui_unicode_stdio_regression.py -q
python -m pytest tests/test_ui_service.py -q
python -m pytest -q
```

The full project suite and a live Streamlit run still need to be validated in the target Windows workspace.
