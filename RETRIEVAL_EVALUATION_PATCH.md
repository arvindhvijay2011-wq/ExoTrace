# ExoTrace retrieval evaluation patch

Adds a fixed source-level benchmark comparing BM25, FAISS dense retrieval, and RRF fusion.

## Run

```powershell
python -m pytest
python -m exotrace.vector.evaluate_retrieval
```

Outputs:

- `data/manifests/retrieval_benchmark_report.json`
- `data/manifests/retrieval_benchmark_report.csv`

The initial 18-question benchmark labels relevant **source pages**, not exact passages. It is
intended as a stable baseline and diagnostic, not as final scientific RAG evaluation. Review
its question labels and add a passage-level gold set before reporting portfolio metrics.

The evaluator uses the existing local frozen corpus and FAISS index. It does not contact NASA,
change Neo4j, download models other than the already-required cached model, or alter the index.
