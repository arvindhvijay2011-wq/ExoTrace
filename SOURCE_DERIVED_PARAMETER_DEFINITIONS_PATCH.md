# ExoTrace: source-derived NASA parameter definitions

This patch replaces the manually authored parameter glossary with a reproducible parser over
`data/raw/reference_pages/archive_parameter_columns.html`, the HTML captured by the existing
NASA reference-page downloader.

## What changes

- `src/exotrace/vector/extract_parameter_definitions.py` parses definition-table rows from the
  frozen NASA HTML, rather than writing per-field definitions or aliases by hand.
- The extractor verifies the HTML against `reference_pages_manifest.json` before processing it.
- Official row descriptions are preserved as source text. Secondary uncertainty/limit field
  documents are generated only from associations explicitly present in the NASA row and marked
  as derived in metadata.
- The manifest records the source URL, source HTML checksum, retrieval time, catalogue snapshot
  identifier/checksum, dataset column coverage, matched/unmatched fields, and output checksum.
- `build_corpus.py` loads only checksum-verified source-derived documents and checks that they
  belong to the same frozen catalogue snapshot and schema.
- No handwritten aliases, curated descriptions, or interpretation notes are used as definitions.

## Apply in the workspace

Extract the patch ZIP into the existing ExoTrace root. Delete the now-unused legacy file
`src/exotrace/vector/data/parameter_glossary.json` after extraction.

Then run:

```powershell
python -m pip install -e ".[dev,vector]"
python -m pytest
python -m exotrace.vector.extract_parameter_definitions --show-unmatched
python -m exotrace.vector.build_corpus --force
python -m exotrace.vector.build_index --force
```

The extractor does not fetch a new live page. It parses the checksum-verified local HTML snapshot.
If that HTML is missing or its checksum differs, extraction stops; it does not fall back to
manual definitions. A future source refresh must be deliberate and should create a new documented
source snapshot.

The `--force` commands replace only derived corpus/index artifacts. They do not alter the raw
NASA CSV snapshot or Neo4j database.
