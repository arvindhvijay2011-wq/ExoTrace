# ExoTrace Answer Synthesis Agent Patch

This patch adds the independent Answer Synthesis Agent and a separate CLI. It reads a saved
investigation JSON report, deduplicates consistent source evidence, calls the existing grounded
answer generator once when evidence is available, and writes a cited answer with provenance.

It replaces `src/exotrace/agents/__init__.py` only to expose the new agent through lazy imports.
It does not change the investigation orchestrator, planner, specialist implementations, FAISS
index, vector corpus, validated CSV snapshot, or Neo4j graph.

Run the targeted tests:

```powershell
python -m pytest tests/test_answer_synthesis.py -q
```

Run the full suite:

```powershell
python -m pytest -q
```
