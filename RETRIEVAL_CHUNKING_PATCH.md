# ExoTrace Retrieval Chunking Improvement

This patch improves the frozen NASA reference-document chunks used by the BM25 + FAISS text retriever.

## Why

The initial retrieval probes found correct NASA sources, but some chunks mixed page-navigation labels, general introductions, and section text. The new chunker respects blank-line paragraph boundaries and short section-heading blocks, puts a meaningful NASA page title on each chunk, records section heading and word count metadata, and removes a repeated generic `In Depth - NASA Science` page chrome title.

The patch also updates the Sentence Transformers embedding-dimension method to the current name, removing the deprecation warning seen in local retrieval output.

## Files

- `src/exotrace/vector/build_corpus.py`
- `src/exotrace/vector/retrieve.py`
- `src/exotrace/vector/build_index.py`
- `tests/test_vector_corpus.py`
- `VECTOR_RETRIEVAL_README.md`

## Apply and rebuild

1. Extract the ZIP into the existing ExoTrace workspace.
2. Run `python -m pytest`.
3. Rebuild the derived corpus: `python -m exotrace.vector.build_corpus --force`.
4. Rebuild the derived FAISS index: `python -m exotrace.vector.build_index --force`.
5. Retest the transit, radial-velocity, and insolation retrieval queries.

Do not rerun NASA downloads, modify the raw/validated catalogue snapshot, or re-import into Neo4j. The patch only changes derived vector text chunks and the embedding-dimension API call. Because the corpus changes, the FAISS index must be rebuilt to keep checksums aligned.
