"""Offline unit tests for ExoTrace's Neo4j graph importer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from exotrace.graph.build_graph import (
    _batched,
    _publication_details,
    classify_insolation,
    load_snapshot_bundle,
    prepare_graph_rows,
    to_neo4j_scalar,
    validate_ingestion_frame,
)


def sample_frame() -> pd.DataFrame:
    """Create a minimal PSCompPars-shaped DataFrame for unit tests."""
    return pd.DataFrame(
        [
            {
                "pl_name": "Planet A b",
                "hostname": "Star A",
                "pl_orbper": 10.5,
                "pl_insol": 0.0,
                "pl_insol_reflink": '<a refstr="CALCULATED_VALUE">Calculated Value</a>',
                "discoverymethod": "Transit",
                "disc_facility": "Observatory A",
                "disc_refname": '<a href="/ref/1">Author et al. 2020</a>',
            },
            {
                "pl_name": "Planet B b",
                "hostname": "Star A",
                "pl_orbper": None,
                "pl_insol": 3.2,
                "pl_insol_reflink": "",
                "discoverymethod": "Radial Velocity",
                "disc_facility": "Observatory B",
                "disc_refname": None,
            },
        ]
    )


def test_missing_numeric_values_become_none_and_zero_is_preserved() -> None:
    assert to_neo4j_scalar(float("nan")) is None
    assert to_neo4j_scalar(float("inf")) is None
    assert to_neo4j_scalar(0.0) == 0.0
    assert to_neo4j_scalar("  Transit ") == "Transit"


def test_insolation_quality_marks_calculated_zero_without_rewriting_value() -> None:
    ref = '<a refstr="CALCULATED_VALUE">Calculated Value</a>'
    assert classify_insolation(0.0, ref) == "calculated_zero_requires_caution"
    assert classify_insolation(0.0, "paper reference") == "source_zero_requires_caution"
    assert classify_insolation(None, ref) == "missing"
    assert classify_insolation(12.5, ref) == "calculated_source_value"


def test_publication_details_extract_visible_text_and_preserve_identity() -> None:
    reference_id, display_name, href = _publication_details(
        '<a href="/ref/1">Author et al. 2020</a>'
    )
    assert reference_id == hashlib.sha256(
        '<a href="/ref/1">Author et al. 2020</a>'.encode("utf-8")
    ).hexdigest()
    assert display_name == "Author et al. 2020"
    assert href == "/ref/1"


def test_prepare_graph_rows_preserves_row_provenance_and_missing_fields() -> None:
    frame = sample_frame()
    rows = prepare_graph_rows(
        frame,
        snapshot_id="PSCompPars::sha256",
        source_file="data/raw/example.csv",
        source_sha256="sha256",
    )
    assert len(rows) == 2
    assert rows[0]["record_id"] == "PSCompPars::sha256::Planet A b"
    assert rows[0]["record_properties"]["pl_orbper"] == 10.5
    assert rows[0]["record_properties"]["insolation_quality_status"] == (
        "calculated_zero_requires_caution"
    )
    assert "pl_orbper" in rows[1]["record_properties"]["missing_fields"]
    assert rows[0]["hostname_key"] == rows[1]["hostname_key"]


def test_duplicate_planet_names_are_rejected() -> None:
    frame = sample_frame()
    frame.loc[1, "pl_name"] = "Planet A b"
    with pytest.raises(ValueError, match="Duplicate planet names"):
        validate_ingestion_frame(frame)


def test_missing_identity_is_rejected() -> None:
    frame = sample_frame()
    frame.loc[0, "hostname"] = None
    with pytest.raises(ValueError, match="hostname"):
        validate_ingestion_frame(frame)


def test_batches_are_bounded_and_reject_invalid_size() -> None:
    rows = [{"value": value} for value in range(5)]
    batches = list(_batched(rows, 2))
    assert [len(batch) for batch in batches] == [2, 2, 1]
    with pytest.raises(ValueError, match="at least 1"):
        list(_batched(rows, 0))


def test_snapshot_loading_checks_real_file_hashes(tmp_path: Path) -> None:
    raw_dir = tmp_path / "data" / "raw"
    processed_dir = tmp_path / "data" / "processed"
    manifests_dir = tmp_path / "data" / "manifests"
    raw_dir.mkdir(parents=True)
    processed_dir.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)

    frame = sample_frame()
    raw_content = b"pl_name,hostname\nPlanet A b,Star A\nPlanet B b,Star A\n"
    raw_path = raw_dir / "pscomppars_test.csv"
    raw_path.write_bytes(raw_content)
    processed_path = processed_dir / "planets_validated.csv"
    frame.to_csv(processed_path, index=False)

    raw_hash = hashlib.sha256(raw_content).hexdigest()
    processed_hash = hashlib.sha256(processed_path.read_bytes()).hexdigest()
    import json

    (manifests_dir / "validation_report.json").write_text(
        json.dumps(
            {
                "passed": True,
                "row_count": len(frame),
                "column_count": len(frame.columns),
                "raw_file": "data/raw/pscomppars_test.csv",
                "raw_sha256": raw_hash,
                "processed_file": "data/processed/planets_validated.csv",
                "processed_sha256": processed_hash,
                "validated_at_utc": "2026-10-18T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (manifests_dir / "pscomppars_test.manifest.json").write_text(
        json.dumps(
            {
                "source": "NASA Exoplanet Archive",
                "sha256": raw_hash,
                "retrieved_at_utc": "2026-10-18T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    bundle = load_snapshot_bundle(tmp_path)
    assert len(bundle.dataframe) == 2
    assert bundle.source_sha256 == raw_hash
    assert bundle.processed_sha256 == processed_hash
    assert bundle.snapshot_properties["validation_passed"] is True
