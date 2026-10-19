# ExoTrace source-derived NASA schema parser recovery

This is an incremental fix for the source-derived parameter-definition extractor. The prior parser required matching column headers to appear in the same HTML table and only parsed rows that followed those headers. The live frozen NASA HTML exposed a valid but different layout for `pl_orbeccen` and `pl_insol`, causing the extractor to stop.

## What changes

- Keeps the original checksum verification against `reference_pages_manifest.json`.
- Keeps definitions sourced from the frozen NASA HTML only. No parameter wording, definitions, or aliases are hardcoded.
- Adds a positional fallback for rows where the database-field identifier is in the source table's declared field column, or first cell when a continuation table has no header.
- Restricts fallback field detection to the field column so it cannot mistake `pl_orbeccenlim` in a limit cell for an independent definition row.
- Records the parsing method (`header_mapped` or `positional_row_fallback`) in each extracted document's metadata and manifest counts.
- If core fields remain missing, prints the original source-row cell contents found for each missing field to make further diagnosis evidence-based.
- Adds a regression test representing a NASA-style table whose data rows continue in a separate headerless table.

## Apply

Extract this ZIP directly into the existing ExoTrace project root, allowing the two matching files to be overwritten:

- `src/exotrace/vector/extract_parameter_definitions.py`
- `tests/test_source_parameter_definitions.py`

Then run:

```powershell
python -m pip install -e ".[dev,vector]"
python -m pytest
python -m exotrace.vector.extract_parameter_definitions --show-unmatched
```

The patch does not touch the raw NASA CSV, frozen HTML, Neo4j database, existing corpus, or FAISS index. Do not rebuild the corpus/index until extraction succeeds and its coverage report has been reviewed.
