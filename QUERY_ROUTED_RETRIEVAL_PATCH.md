# ExoTrace Query-Routed Retrieval Patch

## Why this change
The last 18-question source-level benchmark showed: BM25 Hit@5=0.778/MRR@5=0.699; dense Hit@5=1.000/MRR@5=0.972; unweighted RRF Hit@5=0.944/MRR@5=0.789. The benchmark is small and source-level, but this is enough to stop treating RRF as the default without evidence.

## Behavior
- `--strategy auto` routes natural-language questions to dense retrieval.
- Queries containing explicit NASA field IDs such as `pl_orbeccen`, `pl_insol`, or `st_teff` route to BM25.
- Tokenization preserves underscore-delimited identifiers as single tokens.
- `--strategy bm25`, `--strategy dense`, and `--strategy rrf` remain available for comparison.
- The evaluator now reports BM25, dense, RRF, and routed-policy results, compares routed rank with dense rank per query, and includes source-derived parameter definition documents in the reference scope.
- Three exact-field-ID questions were added to the fixed 18-question benchmark, resulting in 21 questions.

No NASA snapshot, corpus, FAISS vector index, or Neo4j data is changed by the patch itself. Since only retrieval and evaluation behavior changes, no corpus or FAISS rebuild is required.

## Local validation
- `45 passed` in the isolated test project used to validate this patch.
- Python byte-compilation passed.
- The benchmark must still be run against the user's local corpus/index to produce real local metrics.
