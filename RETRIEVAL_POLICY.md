# ExoTrace retrieval policy (current)

## Production retrieval

- The retrieval strategy is selected explicitly: `dense`, `bm25`, or `rrf`.
- The default strategy is `dense` because the current 21-question source-level benchmark reported Hit@5=1.000 and MRR@5=0.976 for dense, compared with Hit@5=0.809/MRR@5=0.718 for BM25 and Hit@5=0.952/MRR@5=0.819 for RRF.
- No regular-expression rule routes field identifiers to a specific retrieval algorithm. Use `--strategy bm25` when explicitly testing lexical retrieval, `--strategy rrf` when explicitly testing fusion.
- Document scope is also explicit. The CLI defaults to `references`, which includes frozen NASA reference chunks and source-derived NASA parameter definitions. Use `--scope profiles` for the planet-profile layer, or `--scope all` to search all corpus document types.
- The CLI defaults are declared configuration defaults, not query-dependent heuristics. The values can be changed by the caller.

## Evaluation

- BM25, dense, and RRF are evaluated independently over the same eligible documents for each query.
- The benchmark is a manually curated evaluation fixture: the question text and expected NASA source slugs are labels for measuring retrieval. They are not part of the production vector corpus and must not be presented as model-generated knowledge.
- Source-level metrics measure whether a result originated from an expected NASA page; they do not measure exact-passage relevance or answer correctness.
- Strategy changes are not accepted based on training-set benchmark score alone. Any learned or adaptive routing policy would require a separate development set and an untouched holdout set.

## Scientific content

NASA page text and parameter definitions are derived from frozen source files with checksums. The pipeline must not add hand-authored factual definitions to the knowledge corpus to make benchmark questions pass.
