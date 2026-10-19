# ExoTrace Query-Aware Retrieval Patch

## Why this patch exists

The shared text corpus contains 6,451 templated planet profiles alongside a small set of official NASA explanatory chunks. The profile template includes field labels such as “Orbital eccentricity” even when the query is asking for a conceptual definition. That can cause a generic planet profile to rank above the authoritative NASA parameter-definition passage.

## Changes

- Adds explicit retrieval scopes: `all`, `references`, and `profiles`.
- The CLI defaults to `--scope auto`: definition/explanation-style queries route to official NASA reference chunks; queries mentioning a known planet or sufficiently specific host-star name route to planet profiles; other queries search all documents.
- Scoped BM25 rankings are calculated only over eligible document types.
- For the small 6,565-document corpus, filtered FAISS search scans the whole index and then keeps only eligible document types. This avoids losing good NASA chunks because irrelevant planet profiles consumed the global dense top-k.
- Source-level benchmark evaluation now searches official NASA reference chunks only, consistent with `expected_source_slugs`. The report explicitly records this scope.
- Adds tests for scope selection and filtering.

This is a transparent heuristic router, not a trained classifier. Explicit `--scope` overrides automatic routing.

## Installation

Extract this ZIP into the existing ExoTrace project root and run:

```powershell
python -m pip install -e ".[dev,vector]"
python -m pytest
python -m exotrace.vector.retrieve --query "What does planetary orbital eccentricity describe?" --top-k 10
python -m exotrace.vector.evaluate_retrieval
```

No corpus or FAISS rebuild is needed: this patch changes query-time filtering only, not embedded text or vector order. It does not modify NASA snapshots, manifests, or Neo4j data.

## Interpretation of benchmark numbers

Scores from this patch should not be compared as if the candidate pool were unchanged. The previous source-level benchmark included generated planet profiles even though the labels refer only to official reference-page slugs. The new evaluation aligns the candidate pool with those labels, making it a fairer source-discovery diagnostic. It is still not a passage-level or answer-quality benchmark.
