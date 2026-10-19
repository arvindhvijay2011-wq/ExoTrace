# ExoTrace source-derived NASA schema parser layout fix

This patch addresses the source-row diagnostic where NASA's frozen HTML contains the expected `pl_orbeccen†` and `pl_insol†` rows, yet the extractor still reports those columns missing.

Root cause: the recovery path continued to reuse column indices inferred from a grouped/table header. The source diagnostics show these rows use the field identifier in the first body cell, label in the second, and description in the third. Header-derived indices can be misaligned with those body rows.

## Change

- The recovery path now reads the actual body row positionally from its first cell, rather than trusting potentially misaligned header-map indices.
- It only accepts first-cell names that match columns in the frozen validated CSV.
- It preserves NASA row labels and descriptions verbatim and retains the original source HTML checksum.
- It adds a regression test for grouped/misaligned header columns.
- It does not insert or paraphrase definitions, does not use a manual glossary, and does not modify the raw snapshot, source HTML, Neo4j graph, corpus, or FAISS index.

## Apply

Extract into the existing project root, then run:

```powershell
python -m pip install -e ".[dev,vector]"
python -m pytest
python -m exotrace.vector.extract_parameter_definitions --show-unmatched
```

Do not rebuild the corpus or FAISS index until extraction succeeds and the extracted-field coverage report has been reviewed.
