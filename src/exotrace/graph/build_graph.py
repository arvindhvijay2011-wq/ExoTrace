"""Import a validated NASA PSCompPars snapshot into the ExoTrace Neo4j database.

The importer is designed to be safely re-run. Source records are snapshot-scoped and
preserved as graph nodes, while canonical Planet and HostStar nodes represent entities.
Scientific parameter values are stored on CatalogueRecord nodes to avoid silently merging
composite-table values from different snapshots or references.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from dataclasses import dataclass
from getpass import getpass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_CSV = Path("data/processed/planets_validated.csv")
VALIDATION_REPORT = Path("data/manifests/validation_report.json")
MANIFEST_DIR = Path("data/manifests")
GRAPH_REPORT = Path("data/manifests/graph_build_report.json")
BATCH_SIZE = 250
REQUIRED_COLUMNS = ("pl_name", "hostname")

SCHEMA_STATEMENTS: tuple[str, ...] = (
    "CREATE CONSTRAINT dataset_snapshot_id_unique IF NOT EXISTS "
    "FOR (n:DatasetSnapshot) REQUIRE n.snapshot_id IS UNIQUE",
    "CREATE CONSTRAINT catalogue_record_id_unique IF NOT EXISTS "
    "FOR (n:CatalogueRecord) REQUIRE n.record_id IS UNIQUE",
    "CREATE CONSTRAINT planet_name_unique IF NOT EXISTS "
    "FOR (n:Planet) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT host_star_key_unique IF NOT EXISTS "
    "FOR (n:HostStar) REQUIRE n.canonical_key IS UNIQUE",
    "CREATE CONSTRAINT discovery_method_key_unique IF NOT EXISTS "
    "FOR (n:DiscoveryMethod) REQUIRE n.canonical_key IS UNIQUE",
    "CREATE CONSTRAINT discovery_facility_key_unique IF NOT EXISTS "
    "FOR (n:DiscoveryFacility) REQUIRE n.canonical_key IS UNIQUE",
    "CREATE CONSTRAINT publication_reference_id_unique IF NOT EXISTS "
    "FOR (n:PublicationReference) REQUIRE n.reference_id IS UNIQUE",
    "CREATE INDEX catalogue_record_snapshot_id_idx IF NOT EXISTS "
    "FOR (n:CatalogueRecord) ON (n.snapshot_id)",
)

BASE_IMPORT_QUERY = """
UNWIND $rows AS row
MERGE (record:CatalogueRecord {record_id: row.record_id})
SET record += row.record_properties
MERGE (planet:Planet {name: row.pl_name})
ON CREATE SET planet.canonical_key = row.pl_name_key
MERGE (host:HostStar {canonical_key: row.hostname_key})
ON CREATE SET host.name = row.hostname
MERGE (snapshot:DatasetSnapshot {snapshot_id: row.snapshot_id})
MERGE (snapshot)-[:CONTAINS_RECORD]->(record)
MERGE (record)-[:DESCRIBES_PLANET]->(planet)
MERGE (record)-[:IDENTIFIES_HOST]->(host)
MERGE (host)-[hosting:HOSTS {snapshot_id: row.snapshot_id}]->(planet)
SET hosting.source_record_id = row.record_id
RETURN count(record) AS processed_count
"""

METHOD_IMPORT_QUERY = """
UNWIND $rows AS row
WITH row WHERE row.discovery_method_key IS NOT NULL
MATCH (record:CatalogueRecord {record_id: row.record_id})
MATCH (planet:Planet {name: row.pl_name})
MERGE (method:DiscoveryMethod {canonical_key: row.discovery_method_key})
ON CREATE SET method.name = row.discovery_method
MERGE (record)-[:USES_DISCOVERY_METHOD]->(method)
MERGE (planet)-[relation:DETECTED_BY {snapshot_id: row.snapshot_id}]->(method)
SET relation.source_record_id = row.record_id
RETURN count(*) AS processed_count
"""

FACILITY_IMPORT_QUERY = """
UNWIND $rows AS row
WITH row WHERE row.discovery_facility_key IS NOT NULL
MATCH (record:CatalogueRecord {record_id: row.record_id})
MATCH (planet:Planet {name: row.pl_name})
MERGE (facility:DiscoveryFacility {canonical_key: row.discovery_facility_key})
ON CREATE SET facility.name = row.discovery_facility
MERGE (record)-[:USES_DISCOVERY_FACILITY]->(facility)
MERGE (planet)-[relation:DISCOVERED_AT {snapshot_id: row.snapshot_id}]->(facility)
SET relation.source_record_id = row.record_id
RETURN count(*) AS processed_count
"""

REFERENCE_IMPORT_QUERY = """
UNWIND $rows AS row
WITH row WHERE row.publication_reference_id IS NOT NULL
MATCH (record:CatalogueRecord {record_id: row.record_id})
MATCH (planet:Planet {name: row.pl_name})
MERGE (reference:PublicationReference {reference_id: row.publication_reference_id})
ON CREATE SET
    reference.display_name = row.publication_display_name,
    reference.reference_raw = row.publication_reference_raw,
    reference.href = row.publication_href
MERGE (record)-[:CITES_DISCOVERY_REFERENCE]->(reference)
MERGE (planet)-[relation:HAS_DISCOVERY_REFERENCE {snapshot_id: row.snapshot_id}]->(reference)
SET relation.source_record_id = row.record_id
RETURN count(*) AS processed_count
"""

NODE_LABELS: tuple[str, ...] = (
    "DatasetSnapshot",
    "CatalogueRecord",
    "Planet",
    "HostStar",
    "DiscoveryMethod",
    "DiscoveryFacility",
    "PublicationReference",
)
RELATIONSHIP_TYPES: tuple[str, ...] = (
    "CONTAINS_RECORD",
    "DESCRIBES_PLANET",
    "IDENTIFIES_HOST",
    "HOSTS",
    "USES_DISCOVERY_METHOD",
    "DETECTED_BY",
    "USES_DISCOVERY_FACILITY",
    "DISCOVERED_AT",
    "CITES_DISCOVERY_REFERENCE",
    "HAS_DISCOVERY_REFERENCE",
)


@dataclass(frozen=True)
class SnapshotBundle:
    """Validated data and provenance metadata used for one graph import."""

    dataframe: pd.DataFrame
    snapshot_properties: dict[str, Any]
    snapshot_id: str
    source_sha256: str
    processed_sha256: str
    source_file: str


@dataclass(frozen=True)
class Neo4jSettings:
    """Non-secret Neo4j connection settings."""

    uri: str
    username: str
    database: str

    @classmethod
    def from_environment(cls) -> "Neo4jSettings":
        """Read local connection settings with safe defaults for Neo4j Desktop."""
        return cls(
            uri=os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687").strip(),
            username=os.getenv("NEO4J_USERNAME", "neo4j").strip(),
            database=os.getenv("NEO4J_DATABASE", "exotrace").strip(),
        )


class _ReferenceHTMLParser(HTMLParser):
    """Extract visible anchor text and an optional href from archive reference markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchor_depth = 0
        self.text_parts: list[str] = []
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self.anchor_depth += 1
            if self.href is None:
                self.href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.anchor_depth > 0:
            self.anchor_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.anchor_depth > 0:
            self.text_parts.append(data)


def _is_missing(value: Any) -> bool:
    """Recognize pandas/NumPy missing scalar values safely."""
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(result, bool):
        return result
    if hasattr(result, "item"):
        try:
            return bool(result.item())
        except (TypeError, ValueError):
            return False
    return False


def to_neo4j_scalar(value: Any) -> str | int | float | bool | None:
    """Convert one pandas scalar to a Neo4j-compatible property value."""
    if _is_missing(value):
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed if trimmed else None
    return str(value)


def _text(value: Any) -> str | None:
    """Return trimmed, non-empty text for graph entity keys."""
    normalized = to_neo4j_scalar(value)
    if normalized is None:
        return None
    text_value = str(normalized).strip()
    return text_value or None


def _canonical_key(value: str) -> str:
    """Normalize an entity name for case-insensitive discovery/host identity."""
    return " ".join(value.split()).casefold()


def classify_insolation(value: Any, reference: Any) -> str:
    """Classify insolation data-quality state without modifying the supplied value."""
    normalized = to_neo4j_scalar(value)
    if normalized is None:
        return "missing"
    try:
        numeric_value = float(normalized)
    except (TypeError, ValueError):
        return "unparseable"
    reference_text = _text(reference) or ""
    is_calculated = "CALCULATED_VALUE" in reference_text.upper()
    if numeric_value == 0.0 and is_calculated:
        return "calculated_zero_requires_caution"
    if numeric_value == 0.0:
        return "source_zero_requires_caution"
    if is_calculated:
        return "calculated_source_value"
    return "source_value"


def _publication_details(reference_value: str | None) -> tuple[str | None, str | None, str | None]:
    """Return reference ID, visible label and href while preserving the original text."""
    if not reference_value:
        return None, None, None
    reference_id = hashlib.sha256(reference_value.encode("utf-8")).hexdigest()
    parser = _ReferenceHTMLParser()
    try:
        parser.feed(reference_value)
        parser.close()
    except Exception:
        # The raw reference remains available on the CatalogueRecord regardless.
        return reference_id, reference_value, None
    display_name = " ".join(" ".join(parser.text_parts).split()) or reference_value
    return reference_id, display_name, parser.href


def validate_ingestion_frame(dataframe: pd.DataFrame) -> None:
    """Enforce identity constraints without rejecting legitimate missing measurements."""
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"Required columns are missing: {missing_columns}")
    for column in REQUIRED_COLUMNS:
        normalized = dataframe[column].astype("string").str.strip()
        missing = dataframe[column].isna() | normalized.eq("").fillna(False)
        if bool(missing.any()):
            raise ValueError(
                f"Required identity column {column!r} has {int(missing.sum())} missing values."
            )
    planet_names = dataframe["pl_name"].astype("string").str.strip()
    duplicate_mask = planet_names.duplicated(keep=False)
    if bool(duplicate_mask.any()):
        examples = sorted(set(planet_names[duplicate_mask].dropna().tolist()))[:10]
        raise ValueError(
            "Duplicate planet names found in the snapshot; refusing ambiguous graph ingestion. "
            f"Examples: {examples}"
        )


def prepare_graph_rows(
    dataframe: pd.DataFrame,
    *,
    snapshot_id: str,
    source_file: str,
    source_sha256: str,
) -> list[dict[str, Any]]:
    """Convert each validated catalogue row to a provenance-aware import payload."""
    validate_ingestion_frame(dataframe)
    rows: list[dict[str, Any]] = []

    for row_number, (_, source_row) in enumerate(dataframe.iterrows(), start=2):
        planet_name = _text(source_row["pl_name"])
        hostname = _text(source_row["hostname"])
        # Identity fields were checked by validate_ingestion_frame.
        assert planet_name is not None
        assert hostname is not None

        raw_properties = {
            str(column): to_neo4j_scalar(value)
            for column, value in source_row.items()
        }
        missing_fields = [key for key, value in raw_properties.items() if value is None]
        record_id = f"{snapshot_id}::{planet_name}"
        raw_properties.update(
            {
                "record_id": record_id,
                "snapshot_id": snapshot_id,
                "source_table": "PSCompPars",
                "source_file": source_file,
                "source_sha256": source_sha256,
                "source_row_number": row_number,
                "missing_field_count": len(missing_fields),
                "insolation_quality_status": classify_insolation(
                    source_row.get("pl_insol"), source_row.get("pl_insol_reflink")
                ),
            }
        )
        if missing_fields:
            # Neo4j property lists should be non-empty; omit this property when no fields
            # are missing and retain the explicit zero count above.
            raw_properties["missing_fields"] = missing_fields

        method_name = _text(source_row.get("discoverymethod"))
        facility_name = _text(source_row.get("disc_facility"))
        publication_raw = _text(source_row.get("disc_refname"))
        publication_id, publication_display_name, publication_href = _publication_details(
            publication_raw
        )

        rows.append(
            {
                "snapshot_id": snapshot_id,
                "record_id": record_id,
                "source_row_number": row_number,
                "pl_name": planet_name,
                "pl_name_key": _canonical_key(planet_name),
                "hostname": hostname,
                "hostname_key": _canonical_key(hostname),
                "record_properties": raw_properties,
                "discovery_method": method_name,
                "discovery_method_key": (
                    _canonical_key(method_name) if method_name else None
                ),
                "discovery_facility": facility_name,
                "discovery_facility_key": (
                    _canonical_key(facility_name) if facility_name else None
                ),
                "publication_reference_raw": publication_raw,
                "publication_reference_id": publication_id,
                "publication_display_name": publication_display_name,
                "publication_href": publication_href,
            }
        )
    return rows


def sha256_file(path: Path) -> str:
    """Calculate a file's SHA-256 checksum in bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_snapshot_bundle(project_root: Path = PROJECT_ROOT) -> SnapshotBundle:
    """Load and cross-check the validated CSV and both provenance manifests."""
    report_path = project_root / VALIDATION_REPORT
    if not report_path.exists():
        raise FileNotFoundError(
            f"Validation report not found at {report_path}. Run "
            "`python -m exotrace.data.validate_snapshot` first."
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("passed") is not True:
        raise ValueError("The latest validation report did not pass; refusing graph ingestion.")

    source_file = str(report.get("raw_file", ""))
    processed_file = str(report.get("processed_file", str(PROCESSED_CSV)))
    if not source_file or not report.get("raw_sha256") or not report.get("processed_sha256"):
        raise ValueError("Validation report is missing source paths or checksums.")

    raw_path = project_root / source_file
    processed_path = project_root / processed_file
    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw NASA snapshot referenced by report not found: {raw_path}")
    if not processed_path.is_file():
        raise FileNotFoundError(f"Validated CSV referenced by report not found: {processed_path}")

    actual_raw_sha = sha256_file(raw_path)
    actual_processed_sha = sha256_file(processed_path)
    if actual_raw_sha != report["raw_sha256"]:
        raise ValueError("Raw snapshot SHA-256 differs from validation report; refusing import.")
    if actual_processed_sha != report["processed_sha256"]:
        raise ValueError("Validated CSV SHA-256 differs from validation report; refusing import.")

    archive_manifest_path = project_root / MANIFEST_DIR / f"{raw_path.stem}.manifest.json"
    if not archive_manifest_path.is_file():
        raise FileNotFoundError(
            f"Download manifest referenced by snapshot name was not found: {archive_manifest_path}"
        )
    archive_manifest: dict[str, Any] = json.loads(
        archive_manifest_path.read_text(encoding="utf-8")
    )
    if archive_manifest.get("sha256") != actual_raw_sha:
        raise ValueError("Download manifest SHA-256 differs from raw snapshot.")

    dataframe = pd.read_csv(processed_path, low_memory=False)
    validate_ingestion_frame(dataframe)
    expected_row_count = int(report.get("row_count", -1))
    if expected_row_count != len(dataframe):
        raise ValueError(
            f"Validation report says {expected_row_count} rows but CSV has {len(dataframe)}."
        )

    snapshot_id = f"PSCompPars::{actual_raw_sha}"
    snapshot_properties: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "source": str(archive_manifest.get("source", "NASA Exoplanet Archive")),
        "source_table": "PSCompPars",
        "source_file": source_file.replace("\\", "/"),
        "raw_sha256": actual_raw_sha,
        "processed_file": processed_file.replace("\\", "/"),
        "processed_sha256": actual_processed_sha,
        "row_count": int(len(dataframe)),
        "column_count": int(len(dataframe.columns)),
        "retrieved_at_utc": archive_manifest.get("retrieved_at_utc"),
        "validated_at_utc": report.get("validated_at_utc"),
        "schema_documentation_url": archive_manifest.get("schema_documentation_url"),
        "tap_documentation_url": archive_manifest.get("tap_documentation_url"),
        "archive_doi": archive_manifest.get("archive_doi", "10.26133/NEA2"),
        "validation_passed": True,
    }
    snapshot_properties = {
        key: value for key, value in snapshot_properties.items() if value is not None
    }
    return SnapshotBundle(
        dataframe=dataframe,
        snapshot_properties=snapshot_properties,
        snapshot_id=snapshot_id,
        source_sha256=actual_raw_sha,
        processed_sha256=actual_processed_sha,
        source_file=source_file.replace("\\", "/"),
    )


def _batched(items: Sequence[dict[str, Any]], batch_size: int) -> Iterable[Sequence[dict[str, Any]]]:
    """Yield fixed-size batches for bounded-memory Neo4j transactions."""
    if batch_size < 1:
        raise ValueError("Batch size must be at least 1.")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def _create_schema(session: Any) -> None:
    """Create idempotent constraints and indexes as separate auto-commit queries."""
    for statement in SCHEMA_STATEMENTS:
        # Keep each schema change in its own implicit transaction for compatibility
        # with Neo4j editions/versions that restrict batched schema-write transactions.
        session.run(statement).consume()


def _upsert_snapshot(tx: Any, snapshot_properties: Mapping[str, Any]) -> None:
    """Create or update provenance metadata for the immutable source snapshot."""
    tx.run(
        "MERGE (snapshot:DatasetSnapshot {snapshot_id: $snapshot_id}) "
        "SET snapshot += $properties",
        snapshot_id=snapshot_properties["snapshot_id"],
        properties=dict(snapshot_properties),
    ).consume()


def _execute_batch(tx: Any, query: str, rows: Sequence[dict[str, Any]]) -> int:
    """Execute one parameterized batch and return its processed row count."""
    result = tx.run(query, rows=list(rows))
    record = result.single()
    if record is None:
        raise RuntimeError("Neo4j did not return a batch-import result.")
    return int(record["processed_count"])


def import_graph(
    driver: Any,
    *,
    database: str,
    bundle: SnapshotBundle,
    batch_size: int = BATCH_SIZE,
) -> dict[str, Any]:
    """Idempotently import one validated snapshot and return post-import statistics."""
    rows = prepare_graph_rows(
        bundle.dataframe,
        snapshot_id=bundle.snapshot_id,
        source_file=bundle.source_file,
        source_sha256=bundle.source_sha256,
    )

    with driver.session(database=database) as session:
        _create_schema(session)
        session.execute_write(_upsert_snapshot, bundle.snapshot_properties)

        for batch in _batched(rows, batch_size):
            session.execute_write(_execute_batch, BASE_IMPORT_QUERY, batch)
            session.execute_write(_execute_batch, METHOD_IMPORT_QUERY, batch)
            session.execute_write(_execute_batch, FACILITY_IMPORT_QUERY, batch)
            session.execute_write(_execute_batch, REFERENCE_IMPORT_QUERY, batch)

        node_counts: dict[str, int] = {}
        for label in NODE_LABELS:
            record = session.run(f"MATCH (n:{label}) RETURN count(n) AS count").single()
            node_counts[label] = int(record["count"])

        relationship_counts: dict[str, int] = {}
        for relationship_type in RELATIONSHIP_TYPES:
            record = session.run(
                f"MATCH ()-[r:{relationship_type}]->() RETURN count(r) AS count"
            ).single()
            relationship_counts[relationship_type] = int(record["count"])

        snapshot_record = session.run(
            "MATCH (snapshot:DatasetSnapshot {snapshot_id: $snapshot_id}) "
            "OPTIONAL MATCH (snapshot)-[:CONTAINS_RECORD]->(record:CatalogueRecord) "
            "RETURN count(record) AS count",
            snapshot_id=bundle.snapshot_id,
        ).single()
        snapshot_record_count = int(snapshot_record["count"])

    expected_rows = len(bundle.dataframe)
    if snapshot_record_count != expected_rows:
        raise RuntimeError(
            "Post-import verification failed: expected "
            f"{expected_rows} records for this snapshot, found {snapshot_record_count}."
        )

    quality_counts = Counter(
        classify_insolation(row.get("pl_insol"), row.get("pl_insol_reflink"))
        for _, row in bundle.dataframe.iterrows()
    )
    return {
        "project": "ExoTrace",
        "database": database,
        "snapshot_id": bundle.snapshot_id,
        "source_file": bundle.source_file,
        "source_sha256": bundle.source_sha256,
        "processed_sha256": bundle.processed_sha256,
        "expected_records": expected_rows,
        "verified_snapshot_records": snapshot_record_count,
        "node_counts_database_total": node_counts,
        "relationship_counts_database_total": relationship_counts,
        "insolation_quality_status_counts": dict(quality_counts),
        "import_is_idempotent": True,
        "provenance_model": "CatalogueRecord nodes preserve source-row fields and snapshot identity.",
    }


def parse_args() -> argparse.Namespace:
    """Parse import and dry-run options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate all source hashes and print import counts without connecting to Neo4j.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Rows per transaction batch (default: {BATCH_SIZE}).",
    )
    return parser.parse_args()


def main() -> int:
    """Command-line entry point."""
    args = parse_args()
    if args.batch_size < 1:
        print("ERROR: --batch-size must be at least 1.", file=sys.stderr)
        return 2

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=False)
        bundle = load_snapshot_bundle()
        rows = prepare_graph_rows(
            bundle.dataframe,
            snapshot_id=bundle.snapshot_id,
            source_file=bundle.source_file,
            source_sha256=bundle.source_sha256,
        )

        print(f"Source snapshot: {bundle.source_file}")
        print(f"Source rows: {len(bundle.dataframe):,}")
        print(f"Unique host stars: {bundle.dataframe['hostname'].nunique():,}")
        print(f"Snapshot ID: {bundle.snapshot_id}")
        print("Source checksums: verified")
        if args.dry_run:
            print(f"Prepared import payloads: {len(rows):,}")
            print("Dry run complete. No Neo4j connection was opened and no data was written.")
            return 0

        # Import the driver only for a real database run, keeping unit tests offline-friendly.
        from neo4j import GraphDatabase

        settings = Neo4jSettings.from_environment()
        password = os.getenv("NEO4J_PASSWORD") or getpass(
            f"Neo4j password for {settings.username}@{settings.uri} (database {settings.database}): "
        )
        if not password:
            raise ValueError("Neo4j password cannot be empty.")

        with GraphDatabase.driver(settings.uri, auth=(settings.username, password)) as driver:
            driver.verify_connectivity()
            print(f"Connected to Neo4j at {settings.uri}; database={settings.database}.")
            report = import_graph(
                driver,
                database=settings.database,
                bundle=bundle,
                batch_size=args.batch_size,
            )

        report["built_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
        report_path = PROJECT_ROOT / GRAPH_REPORT
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        print("\nGraph import verified.")
        print(f"Records in this snapshot: {report['verified_snapshot_records']:,}")
        print("Nodes in database:")
        for label, count in report["node_counts_database_total"].items():
            print(f"  {label}: {count:,}")
        print("Relationships in database:")
        for rel_type, count in report["relationship_counts_database_total"].items():
            print(f"  {rel_type}: {count:,}")
        print(f"Report: {report_path.relative_to(PROJECT_ROOT)}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Keep the original exception message visible, especially Neo4j constraint/query errors.
        print(f"ERROR during graph import: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
