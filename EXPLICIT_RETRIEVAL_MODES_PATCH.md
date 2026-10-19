# ExoTrace explicit retrieval modes patch

## What changed

- Removed the query-prefix heuristic that automatically routed `pl_*`, `st_*`, and similar identifiers to BM25.
- Removed query-text scope inference based on a fixed cue list and profile-name substring matching.
- Retrieval now uses explicit modes only: `dense`, `bm25`, or `rrf`.
- The documented CLI defaults are `--strategy dense` and `--scope references`, based on the current benchmark and the goal of conceptual source retrieval. These are explicit defaults, not rules inferred from query text.
- Use `--scope profiles` for planet profiles or `--scope all` for the complete corpus. Use `--strategy bm25` or `--strategy rrf` when deliberately comparing these approaches.
- Evaluation now compares the three independent methods only. It no longer reports a manually routed fourth method as if it were a distinct retrieval algorithm.

## Why

The latest local 21-question report showed:

- BM25: Hit@5 0.809, MRR@5 0.718
- Dense: Hit@5 1.000, MRR@5 0.976
- RRF: Hit@5 0.952, MRR@5 0.819
- Query-routed: Hit@5 1.000, MRR@5 0.952

The query-routed rule did not improve Hit@5 over dense and reduced MRR. Therefore it is removed rather than tuned to these same 21 questions.

## Install

Extract this ZIP directly into the existing ExoTrace project root, allowing the listed files to be overwritten.

## Verify

```powershell
python -m pytest
python -m exotrace.vector.evaluate_retrieval
python -m exotrace.vector.retrieve --query "What does planetary orbital eccentricity describe?" --top-k 10
```

The retrieval command defaults to dense search over NASA reference chunks and source-derived parameter definitions. The parameter corpus, FAISS index, raw snapshot, validation artifacts, and Neo4j database are not included in this patch and are not changed by installing it.

The benchmark fixture remains an intentionally fixed test set with manually curated expected source labels. It is used only to evaluate retrieval and is not fed into production retrieval as knowledge.
