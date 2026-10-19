Patch scope: one existing UI service file plus one new regression test and documentation.

Production change: `src/exotrace/ui/service.py` only.
Added test: `tests/test_ui_unicode_stdio_regression.py`.
Added docs: `docs/WINDOWS_UNICODE_CLI_OUTPUT.md`.

The installer requires the baseline SHA-256 of service.py to match before modifying any project file. It backs up service.py and will not overwrite an existing file with either new filename.
