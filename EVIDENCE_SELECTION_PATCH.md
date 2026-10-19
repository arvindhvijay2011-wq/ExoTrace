# ExoTrace: Conservative Evidence Selection Patch

## Purpose

This patch filters mechanically derived uncertainty/limit association documents before
answer generation, unless the query explicitly targets that associated field or role.
It uses existing corpus provenance metadata (`definition_extraction`,
`parameter_field`, and `related_parameter_field`). It does not hardcode scientific
facts, parameter definitions, individual field names, question-specific answers, or
retrieval strategy routing.

## Files

- `src/exotrace/answering/evidence_selection.py` — new complete selection module.
- `src/exotrace/answering/ask.py` — complete CLI module wired to evidence selection.
- `tests/test_evidence_selection.py` — focused offline tests.

No changes are made to FAISS, the vector corpus, Neo4j, retrieval strategy defaults,
model configuration, or the OpenAI API client.

## Apply

Extract this ZIP into the ExoTrace project root, preserving the `src` and `tests`
folders. The `ask.py` file is intentionally a complete replacement.

## Validate

```powershell
python -m pytest tests/test_evidence_selection.py -q
python -m pytest -q
```

Then test the question that exposed the redundant citation:

```powershell
python -m exotrace.answering.ask --query "What does planetary orbital eccentricity describe?" --save-json data/manifests/last_answer.json
```

Expected behavior: when the primary parent definition is retrieved, an associated limit
or uncertainty record is filtered from a general parent-definition query. If the query
explicitly asks about the associated field or role, the derived record remains eligible.

## Important limitation

This is a deterministic evidence-selection guard, not a semantic entailment verifier.
Citation-ID validation still only proves that a cited ID belongs to the selected evidence
set. The answer text and each citation must still be audited for actual source support.
