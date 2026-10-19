# ExoTrace Vector Retrieval Patch

This patch adds a reproducible local text-retrieval layer over (1) frozen, official NASA
exoplanet reference pages and (2) source-linked profiles generated from the currently
validated `PSCompPars` snapshot.

## Data flow

1. `python -m exotrace.vector.fetch_reference_docs` captures a small allowlist of official
   NASA explanatory and archive-schema pages into `data/raw/reference_pages/`, writes a
   normalized text export to `data/processed/reference_pages.jsonl`, and records hashes and
   retrieval time in `data/manifests/reference_pages_manifest.json`.
2. `python -m exotrace.vector.build_corpus` verifies the existing NASA snapshot and creates
   `data/processed/vector_corpus.jsonl` plus `data/manifests/vector_corpus_manifest.json`.
   It chunks explanatory pages by paragraph and section boundaries, attaches section metadata, and creates one compact profile per planet.
3. `python -m exotrace.vector.build_index` embeds the fixed corpus with
   `sentence-transformers/all-MiniLM-L6-v2`, normalizes the embeddings, and writes a FAISS
   `IndexFlatIP` index plus a provenance manifest.
4. `python -m exotrace.vector.retrieve --query "How does the transit method find a planet?"`
   returns results fused from BM25 and FAISS rankings with Reciprocal Rank Fusion (RRF).

## Install

Run from the project root:

```powershell
python -m pip install -e ".[dev,vector]"
```

The first fetch and model-index build require Internet access. After the reference pages and
model weights are downloaded, the corpus and FAISS index are local static artifacts. The fetch
step refuses to overwrite an existing page snapshot unless `--refresh` is explicitly supplied.
The corpus and index steps refuse to overwrite an existing corpus/index unless `--force` is
explicitly supplied. When the corpus changes, always rebuild the index.

## Important evidence policy

- Numerical answers must be retrieved from source-linked Neo4j `CatalogueRecord` properties,
  not inferred from vector similarity.
- Generated planet profiles are a discovery layer, not independent primary sources.
- Missing measurements remain unreported; no scientific measurements are imputed.
- The source's uncertainty and limit fields are represented in the generated profile text; the canonical source-linked Neo4j record remains authoritative.
- The profile labels suspicious zero-insolation values with a caution status but does not
  rewrite the downloaded or validated CSV values.
- BM25 and FAISS produce separate rankings. RRF fuses ranks, not their non-comparable raw scores.
- This first patch implements lexical+dense **text** hybrid retrieval. Query routing and graph
  expansion will be evaluated separately rather than hidden inside this retriever.

## Outputs

- `data/raw/reference_pages/*.html`
- `data/processed/reference_pages.jsonl`
- `data/manifests/reference_pages_manifest.json`
- `data/processed/vector_corpus.jsonl`
- `data/manifests/vector_corpus_manifest.json`
- `data/processed/vector_index/exotrace.faiss`
- `data/manifests/vector_index_manifest.json`
