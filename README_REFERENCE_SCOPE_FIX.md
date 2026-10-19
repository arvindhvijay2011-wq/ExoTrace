# ExoTrace retrieval-scope fix

## Root cause

The `references` scope in `src/exotrace/vector/retrieve.py` allowed only
`official_nasa_reference_chunk`. This excluded the newly extracted
`official_nasa_parameter_definition` documents even though they were present in
the corpus and FAISS index.

## Apply

Run `python .\apply_reference_scope_fix.py` from the ExoTrace project root after
extracting this patch there. The script:

- adds the `PARAMETER_DEFINITION_DOC_TYPE` constant;
- includes it in the `references` allowlist;
- creates a `.pre_reference_scope_fix.bak` backup if one does not already exist;
- fails without writing if the expected source fragments aren't found exactly once.

The patch does not rebuild the corpus or FAISS index and does not access Neo4j.

## Verify

Run:

```powershell
python -m pytest
python -m exotrace.vector.retrieve --query "What does planetary orbital eccentricity describe?" --top-k 10
```

The query should now be allowed to rank both original NASA reference chunks and
source-derived NASA parameter-definition documents.
