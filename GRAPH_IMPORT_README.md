# ExoTrace Neo4j importer patch

This patch changes the graph destination from an in-memory NetworkX graph to your persistent
Neo4j Desktop database. It does not modify or download any NASA data.

## 1. Overlay files into the existing project root

Extract this ZIP directly into the `ExoTrace` folder (the same folder that contains
`pyproject.toml`, `src`, `tests`, and `data`). Allow `pyproject.toml` to be overwritten.
The patch adds `src/exotrace/graph/build_graph.py`, graph schema documentation, an example
local configuration, and offline unit tests.

## 2. Install dependencies and run tests

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

## 3. Configure the local Neo4j connection

Copy the example config. The `NEO4J_PASSWORD` line is intentionally commented out; the importer
will prompt for the password securely if the environment variable isn't set.

```powershell
Copy-Item .env.example .env
```

Defaults match the tested local setup: `neo4j://127.0.0.1:7687`, username `neo4j`, database
`exotrace`. Edit `.env` only if your local settings differ. `.env` is excluded from Git.
Never commit passwords or send them in chat.

## 4. Validate the import inputs without writing to Neo4j

```powershell
python -m exotrace.graph.build_graph --dry-run
```

The dry run verifies the raw snapshot checksum, the validated CSV checksum, the validation
report, and the source manifest. It does not connect to Neo4j or write data.

## 5. Import into Neo4j

Ensure the `ExoTrace` instance is running and the `exotrace` database is selected/available,
then run:

```powershell
python -m exotrace.graph.build_graph
```

The importer creates uniqueness constraints, imports in batches, and verifies the source
record count in the selected snapshot. It writes `data/manifests/graph_build_report.json`.
Re-running the command for the same snapshot is designed to be idempotent.

## Data and safety notes

- The importer refuses to run if source files don't match the SHA-256 checksums in the reports.
- The raw and validated CSV files are not modified.
- It writes only to the `exotrace` database selected by configuration; check the database name
  before importing. It does not perform any deletes.
- Node and relationship totals in the report are database-wide totals, while the verified
  catalogue-record count is scoped to the imported snapshot.
- Scientific values are kept on `CatalogueRecord` nodes; do not flatten composite-table
  parameters onto shared star nodes.
