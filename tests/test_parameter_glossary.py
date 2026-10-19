"""Regression tests ensuring parameter definitions are extracted from NASA's source schema."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from exotrace.vector import extract_parameter_definitions as extractor
from exotrace.vector.build_corpus import load_source_parameter_documents

SOURCE_URL = "https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html"


def _schema_html() -> str:
    """Return a small HTML-table fixture shaped like NASA's schema, not answer cards."""
    return """
    <html><body>
      <h2>Planet Parameters</h2>
      <table>
        <tr>
          <th>Database Column Name</th><th>Table Label</th><th>Description</th>
          <th>Uncertainties Column (positive +) (negative -)</th><th>Limit Column</th>
          <th>In PS Table</th><th>In PSCompPars Table</th>
        </tr>
        <tr>
          <td>pl_orbeccen†</td><td>Eccentricity</td>
          <td>Amount by which the orbit of the planet deviates from a perfect circle</td>
          <td>(+) pl_orbeccenerr1 (-) pl_orbeccenerr2</td><td>pl_orbeccenlim</td><td>X</td><td>X</td>
        </tr>
        <tr>
          <td>pl_orbeccen_reflink</td><td>Eccentricity Reference</td>
          <td>Reference of publication used for given parameter set</td>
          <td></td><td></td><td></td><td>X</td>
        </tr>
      </table>
    </body></html>
    """


def test_parser_preserves_verbatim_source_description_and_relationships() -> None:
    html = _schema_html()
    raw_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    rows = extractor._parse_source_rows(html, SOURCE_URL, raw_sha)
    eccentricity = next(row for row in rows if row["field"] == "pl_orbeccen")

    assert eccentricity["label"] == "Eccentricity"
    assert eccentricity["description"] == (
        "Amount by which the orbit of the planet deviates from a perfect circle"
    )
    assert eccentricity["uncertainty_fields"] == [
        {"polarity": "positive", "field": "pl_orbeccenerr1"},
        {"polarity": "negative", "field": "pl_orbeccenerr2"},
    ]
    assert eccentricity["limit_field"] == "pl_orbeccenlim"
    assert eccentricity["in_ps"] is True
    assert eccentricity["in_pscomppars"] is True
    assert eccentricity["source_html_sha256"] == raw_sha


def test_source_row_document_contains_published_words_not_curated_aliases() -> None:
    html = _schema_html()
    raw_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    row = next(
        row for row in extractor._parse_source_rows(html, SOURCE_URL, raw_sha)
        if row["field"] == "pl_orbeccen"
    )
    doc = extractor._build_document(row)

    assert doc["doc_type"] == "official_nasa_parameter_definition"
    assert doc["doc_id"] == "reference:archive_parameter_columns:chunk:field_pl_orbeccen"
    assert row["description"] in doc["text"]
    assert "Common question wording and aliases" not in doc["text"]
    assert doc["metadata"]["definition_extraction"] == "official_table_row"


def test_uncertainty_document_is_explicitly_marked_as_mechanically_derived() -> None:
    html = _schema_html()
    raw_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    parent = next(
        row for row in extractor._parse_source_rows(html, SOURCE_URL, raw_sha)
        if row["field"] == "pl_orbeccen"
    )
    doc = extractor._build_document(
        {
            "field": "pl_orbeccenerr1",
            "parent": parent,
            "polarity": "positive",
            "source_url": SOURCE_URL,
        },
        extraction_kind="derived_association",
    )

    assert "positive (upper) uncertainty" in doc["text"]
    assert doc["metadata"]["definition_extraction"] == "derived_from_official_uncertainty_association"
    assert doc["metadata"]["related_parameter_field"] == "pl_orbeccen"


def test_extractor_uses_frozen_html_and_records_source_checksums(tmp_path: Path, monkeypatch) -> None:
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)
    html = _schema_html().encode("utf-8")
    raw_path = raw_dir / "archive_parameter_columns.html"
    raw_path.write_bytes(html)
    raw_sha = hashlib.sha256(html).hexdigest()
    manifest_path = tmp_path / "data" / "manifests" / "reference_pages_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "retrieved_at_utc": "2026-10-18T15:12:10+00:00",
                "pages": [
                    {
                        "slug": extractor.SOURCE_SLUG,
                        "status": "downloaded",
                        "url": SOURCE_URL,
                        "raw_file": "data/raw/archive_parameter_columns.html",
                        "raw_sha256": raw_sha,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(extractor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(extractor, "REFERENCE_MANIFEST_PATH", Path("data/manifests/reference_pages_manifest.json"))
    monkeypatch.setattr(extractor, "OUTPUT_JSONL", Path("data/processed/parameter_definitions.jsonl"))
    monkeypatch.setattr(extractor, "OUTPUT_MANIFEST", Path("data/manifests/parameter_definitions_manifest.json"))
    monkeypatch.setattr(
        extractor,
        "load_snapshot_bundle",
        lambda _root: SimpleNamespace(
            dataframe=pd.DataFrame(columns=["pl_orbeccen", "pl_orbeccenerr1", "pl_orbeccenerr2", "pl_orbeccenlim"]),
            snapshot_id="PSCompPars::test-snapshot",
            source_file="data/raw/sample.csv",
            source_sha256="sample-csv-sha",
        ),
    )

    manifest = extractor.extract_parameter_definitions()
    output = tmp_path / "data/processed/parameter_definitions.jsonl"
    docs = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    by_field = {doc["metadata"]["parameter_field"]: doc for doc in docs}

    assert manifest["manual_glossary_used"] is False
    assert manifest["source_raw_sha256"] == raw_sha
    assert by_field["pl_orbeccen"]["metadata"]["definition_extraction"] == "official_table_row"
    assert by_field["pl_orbeccenerr1"]["metadata"]["definition_extraction"] == "derived_from_official_uncertainty_association"
    assert by_field["pl_orbeccenlim"]["metadata"]["definition_extraction"] == "derived_from_official_limit_association"


def test_definition_loader_rejects_checksum_or_snapshot_mismatch(tmp_path: Path) -> None:
    docs_path = tmp_path / "defs.jsonl"
    manifest_path = tmp_path / "manifest.json"
    raw_sha = "source-hash"
    doc = {
        "doc_id": "reference:archive_parameter_columns:chunk:field_pl_orbeccen",
        "doc_type": "official_nasa_parameter_definition",
        "title": "Eccentricity (pl_orbeccen)",
        "text": "The orbit deviates from a perfect circle.",
        "metadata": {
            "parameter_field": "pl_orbeccen",
            "source_url": SOURCE_URL,
            "source_raw_sha256": raw_sha,
        },
    }
    payload = (json.dumps(doc) + "\n").encode("utf-8")
    docs_path.write_bytes(payload)
    manifest_path.write_text(
        json.dumps(
            {
                "output_jsonl_sha256": hashlib.sha256(payload).hexdigest(),
                "catalogue_snapshot_id": "wrong-snapshot",
                "catalogue_source_sha256": "csv-hash",
                "dataset_columns": ["pl_orbeccen"],
                "manual_glossary_used": False,
                "source_raw_sha256": raw_sha,
            }
        ),
        encoding="utf-8",
    )

    try:
        load_source_parameter_documents(
            docs_path,
            manifest_path,
            snapshot_id="correct-snapshot",
            source_sha256="csv-hash",
            dataset_columns=["pl_orbeccen"],
        )
    except ValueError as exc:
        assert "different catalogue snapshot" in str(exc)
    else:
        raise AssertionError("Expected mismatched snapshot to be rejected")
