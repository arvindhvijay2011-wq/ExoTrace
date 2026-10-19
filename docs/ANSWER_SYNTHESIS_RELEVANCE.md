# ExoTrace synthesis relevance improvement

## Purpose

This additive patch improves source selection and answer focus without adding an agent or a second model call.

## Changes

- The Answer Synthesis Agent now reuses `select_answer_evidence`, the existing provenance-driven selector.
- Mechanically derived parameter association records are removed from the synthesis context when the user's question does not target that associated field or role. This decision is based on source metadata and query context; there is no hardcoded `pl_orbeccen` exception.
- If the user explicitly asks about an associated field/role, relevant association evidence remains available.
- The general answer-generation policy now directs the model to include only information needed to answer the user's question, avoid adjacent facts that do not answer it, and avoid redundant paraphrases.
- The direct answer CLI and investigation CLI are unchanged.

## Limitations

The metadata selector only handles mechanically derived association records identified by the corpus's own provenance metadata. It is not a general semantic relevance model and does not filter every unrelated passage. The prompt changes guide synthesis but do not guarantee perfect output. Citation-ID validation is structural, not a proof of entailment.

## Installation

Extract the ZIP at the ExoTrace project root. Back up these existing files first:

- `src/exotrace/agents/synthesis.py`
- `src/exotrace/answering/grounded_answer.py`
- `tests/test_answer_synthesis.py`

No new dependency is required. No dataset, manifest, FAISS index, vector corpus, or Neo4j data is modified.

## Tests

Run:

```powershell
python -m pytest tests/test_answer_synthesis.py tests/test_grounded_answer.py tests/test_evidence_selection.py -q
python -m pytest -q
```

In the assembled environment used to prepare this patch: **209 passed, 1 skipped** across the full test suite. The live OpenAI API was not called during tests.
