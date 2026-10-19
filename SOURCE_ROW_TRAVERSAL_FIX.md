# ExoTrace: global source-row traversal fix

## Root cause

The source diagnostics show that `soup.find_all("tr")` returns the `pl_orbeccen` and `pl_insol` rows, while iterating `table.find_all("tr")` over each discovered table does not. This means BeautifulSoup parses those rows as `tr` elements that are not descendants of a `<table>` element. The parser previously searched only table descendants, so it silently missed them.

## Change

The first-pass parser now iterates `soup.find_all("tr")` once across the document and uses the nearest table for section context when present. Orphan continuation rows receive the generic section label; their source text, URL, and checksum are preserved. No definitions or aliases are hardcoded.

## Apply

Extract these files directly into the existing ExoTrace project root, overwriting the parser and its test file only. Then run:

```powershell
python -m pip install -e ".[dev,vector]"
python -m pytest
python -m exotrace.vector.extract_parameter_definitions --show-unmatched
```

This patch does not include or overwrite source data, manifests, corpus, indexes, `.env`, or Neo4j database contents.
