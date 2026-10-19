# Initial engineering decisions

1. **Use `PSCompPars` for the first pass.** It provides one row per planet and supports a compact population-analysis prototype. Its composite nature is a known caveat, not hidden.
2. **Keep the raw snapshot immutable.** The downloader writes timestamped files plus SHA-256 manifests.
3. **Validate before indexing.** Duplicate planet identifiers and missing identity keys are errors; missing scientific parameters are expected and must remain missing.
4. **Preserve provenance.** Error columns, limit flags, and per-parameter reference links remain in the selected schema.
5. **Do not force every question through every retriever.** Numerical questions use structured querying; relation questions use the graph; explanatory questions use text retrieval; hybrid questions use only the necessary sources.
6. **Evaluate before tuning.** Keep a fixed question set and compare structured, lexical, vector, graph, and hybrid baselines before adding a reranker.
