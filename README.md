# ExoTrace

**ExoTrace** is a two-day prototype of an agentic scientific investigation assistant. It will combine:

- deterministic queries for exact scientific measurements;
- a knowledge graph for explicit relationships between host stars, planets, and discovery metadata;
- lexical and dense retrieval for explanatory text;
- evidence assembly, source traceability, and conservative answer verification.

The first milestone is deliberately data-first. We will freeze an Exoplanet Archive snapshot, validate it, and only then build graph/vector indexes. We will not treat generated planet summaries as independent scientific sources.

## Data source

- NASA Exoplanet Archive TAP service: <https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html>
- `PSCompPars` table definitions: <https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html>
- About composite parameters and caveats: <https://exoplanetarchive.ipac.caltech.edu/docs/pscp_about.html>
- Archive data DOI to acknowledge when appropriate: `10.26133/NEA2`

`PSCompPars` contains one row per confirmed planet and is useful for population-level exploration. Its values may originate from different sources and may be calculated, so each selected field's uncertainty/limit/reference fields should be preserved. Do not interpret one row as a fully self-consistent solution for every parameter.

## Setup (Windows PowerShell, VS Code terminal)

Use Python 3.11 or 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell blocks environment activation, you can invoke the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Milestone 1: fetch and validate the data

Run these commands from the project root (`ExoTrace`):

```powershell
python -m exotrace.data.fetch_archive
python -m exotrace.data.validate_snapshot
python -m pytest
```

The first command downloads a **dated local snapshot** of the selected `PSCompPars` columns to `data/raw/` and records its query, retrieval timestamp, row count, schema, and SHA-256 checksum in `data/manifests/`.

The second command reads the saved snapshot without modifying it, creates a normalized working CSV in `data/processed/`, and writes a validation report. A successful download is not considered automatically clean: inspect the report for duplicate identifiers, missing keys, and missingness by field before indexing anything.

The repository intentionally does not contain a downloaded live snapshot. Run the fetch command in your environment to create one; this keeps data provenance explicit and avoids pretending that a file was fetched when it was not.

## Planned two-day scope

### Day 1

1. Freeze and validate the archive data.
2. Choose a bounded, reproducible working subset if needed.
3. Build graph entities and edges using only source-supported relationships.
4. Curate authoritative NASA explanatory documents for vector retrieval.
5. Preserve IDs, source links, units, uncertainty fields, limit flags, and provenance.

### Day 2

1. Implement query routing across structured lookup, graph traversal, and semantic/lexical retrieval.
2. Fuse BM25 and dense rankings with Reciprocal Rank Fusion (RRF).
3. Assemble and validate compact evidence packs.
4. Evaluate around 30–50 fixed questions, including unanswerable ones.
5. Add a small Streamlit interface and report results honestly.

Learned fusion, domain-specific reranker experiments, complex multi-agent orchestration, and large-scale evaluation are out of scope for the two-day prototype.

## Quality principles

- Use structured queries for exact numbers, filtering, sorting, and comparisons.
- Use graph traversal for verified relationships.
- Use text retrieval for explanations and parameter definitions.
- Treat missing values as missing; do not silently impute them.
- Keep lower/upper-limit flags and asymmetric uncertainty values.
- Keep the source record or source URL attached to each claim.
- Abstain when the available evidence does not support an answer.
