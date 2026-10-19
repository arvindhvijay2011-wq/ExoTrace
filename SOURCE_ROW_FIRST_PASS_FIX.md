# ExoTrace source-row-first parser fix

This patch fixes source extraction in `src/exotrace/vector/extract_parameter_definitions.py`.

## Why

The frozen NASA HTML diagnostics showed that rows for `pl_insol†` and `pl_orbeccen†` exist in the source HTML and that `_field_name()` normalizes them correctly, but the parser's returned rows contained only `pl_orbper`. The header-mapped pass was therefore not a dependable first pass for the observed source body layout.

## What changes

The parser now first scans the frozen HTML table body rows using their observed source cell order:

1. First cell: database field identifier.
2. Second cell: table label.
3. Third cell: source description.
4. Following cells: uncertainty associations, limit field, and table-availability flags.

A candidate is only accepted if the field matches the validated dataset schema (when provided), has an identifier-like form, and has source label/description text. The definition wording is copied from the HTML; no glossary definitions or aliases are handwritten. The existing header-mapped parser remains as a fallback for any source rows that do not use this layout.

The source-first extraction method is recorded as `source_row_first_cell` in metadata.

## Files

- `src/exotrace/vector/extract_parameter_definitions.py`
- `tests/test_source_parameter_definitions.py`

## Apply

Extract the ZIP into the existing ExoTrace project root, overwriting only the two matching files. Then run:

```powershell
python -m pip install -e ".[dev,vector]"
python -m pytest
python -m exotrace.vector.extract_parameter_definitions --show-unmatched
```

Expected full test-suite result in the isolated patch test environment: 40 passed. The real local NASA extraction still must be run and checked in the user's workspace.
