"""Offline tests for the Literature and Catalogue read-only tools."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from exotrace.tools.catalogue_lookup import CatalogueLookupConfig, CatalogueRecordLookupTool
from exotrace.tools.contracts import ToolRequest, ToolStatus
from exotrace.tools.literature_search import LiteratureSearchConfig, LiteratureSearchTool


class FakeRetriever:
    """Minimal retriever test double that records calls and returns fixed documents."""

    def __init__(self, documents: list[dict[str, Any]] | None = None) -> None:
        self.documents = documents or []
        self.calls: list[dict[str, Any]] = []
        self.corpus_sha256 = "vector-corpus-sha"
        self.corpus_manifest = {"snapshot_id": "test-snapshot"}

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        scope: str = "references",
        strategy: str = "dense",
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {"query": query, "top_k": top_k, "scope": scope, "strategy": strategy}
        )
        return self.documents[:top_k]


def make_document(
    doc_id: str = "reference:parameter:pl_orbeccen",
    text: str = "Amount by which the orbit deviates from a perfect circle.",
) -> dict[str, Any]:
    """Create a retrieval result shaped like the current vector corpus output."""
    return {
        "doc_id": doc_id,
        "doc_type": "official_nasa_parameter_definition",
        "title": "Eccentricity (pl_orbeccen)",
        "text": text,
        "metadata": {
            "source_url": "https://example.test/nasa-parameter-doc",
            "parameter_field": "pl_orbeccen",
            "record_id": "record-1",
        },
        "retrieval": {"selected_rank": 1, "strategy": "dense", "selected_score": 0.9},
    }


def build_catalogue_files(tmp_path: Path) -> tuple[Path, Path, str]:
    """Create a small validated catalogue and matching validation report."""
    catalogue_path = tmp_path / "planets_validated.csv"
    fieldnames = (
        "pl_name",
        "hostname",
        "pl_orbper",
        "pl_orbper_reflink",
        "pl_rade",
    )
    rows = [
        {
            "pl_name": "Planet A",
            "hostname": "Star A",
            "pl_orbper": "12.500000",
            "pl_orbper_reflink": "https://paper.test/planet-a",
            "pl_rade": "1.25",
        },
        {
            "pl_name": "Planet B",
            "hostname": "Star B",
            "pl_orbper": "25.000000",
            "pl_orbper_reflink": "https://paper.test/planet-b",
            "pl_rade": "2.10",
        },
    ]
    with catalogue_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    catalogue_sha = hashlib.sha256(catalogue_path.read_bytes()).hexdigest()
    raw_sha = hashlib.sha256(b"source snapshot bytes").hexdigest()
    report_path = tmp_path / "validation_report.json"
    report_path.write_text(
        json.dumps(
            {
                "passed": True,
                "row_count": len(rows),
                "raw_sha256": raw_sha,
                "processed_sha256": catalogue_sha,
                "processed_file": "data/processed/planets_validated.csv",
            }
        ),
        encoding="utf-8",
    )
    return catalogue_path, report_path, raw_sha


def make_catalogue_tool(tmp_path: Path, *, max_limit: int = 100) -> tuple[CatalogueRecordLookupTool, str]:
    catalogue_path, report_path, raw_sha = build_catalogue_files(tmp_path)
    tool = CatalogueRecordLookupTool(
        config=CatalogueLookupConfig(
            catalogue_path=catalogue_path,
            validation_report_path=report_path,
            default_limit=min(10, max_limit),
            max_limit=max_limit,
        )
    )
    return tool, raw_sha


def test_literature_tool_calls_existing_retriever_with_fixed_reference_scope() -> None:
    retriever = FakeRetriever([make_document()])
    tool = LiteratureSearchTool(
        retriever,
        config=LiteratureSearchConfig(strategy="dense", default_top_k=4, max_top_k=9),
    )

    result = tool.execute(
        ToolRequest(
            call_id="call-1",
            tool_id="literature.search",
            arguments={"query": "What does eccentricity describe?", "top_k": 2},
        )
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert retriever.calls == [
        {
            "query": "What does eccentricity describe?",
            "top_k": 2,
            "scope": "references",
            "strategy": "dense",
        }
    ]
    assert result.evidence[0].evidence_id == "literature:reference:parameter:pl_orbeccen"
    assert result.evidence[0].source_uri == "https://example.test/nasa-parameter-doc"
    assert result.evidence[0].record_id == "record-1"
    assert result.evidence[0].metadata["retrieval"]["selected_rank"] == 1


def test_literature_tool_rejects_scope_override_and_top_k_over_configured_cap() -> None:
    retriever = FakeRetriever([make_document()])
    tool = LiteratureSearchTool(
        retriever,
        config=LiteratureSearchConfig(default_top_k=2, max_top_k=3),
    )

    scope_result = tool.execute(
        ToolRequest(
            call_id="call-1",
            tool_id="literature.search",
            arguments={"query": "definition", "scope": "profiles"},
        )
    )
    limit_result = tool.execute(
        ToolRequest(
            call_id="call-2",
            tool_id="literature.search",
            arguments={"query": "definition", "top_k": 4},
        )
    )

    assert scope_result.status is ToolStatus.FAILED
    assert scope_result.error_code == "unsupported_arguments"
    assert limit_result.status is ToolStatus.FAILED
    assert limit_result.error_code == "invalid_top_k"
    assert retriever.calls == []


def test_literature_tool_skips_malformed_docs_and_marks_partial_result() -> None:
    retriever = FakeRetriever(
        [
            make_document(),
            {"doc_id": "no-text", "text": " "},
            make_document(),
        ]
    )
    tool = LiteratureSearchTool(retriever)

    result = tool.execute(
        ToolRequest("call-1", "literature.search", {"query": "eccentricity"})
    )

    assert result.status is ToolStatus.PARTIAL
    assert len(result.evidence) == 1
    assert result.data["malformed_documents_skipped"] == 2


def test_literature_tool_reports_empty_success_as_no_evidence() -> None:
    tool = LiteratureSearchTool(FakeRetriever([]))
    result = tool.execute(
        ToolRequest("call-1", "literature.search", {"query": "unmatched query"})
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.evidence == ()
    assert result.data["returned_count"] == 0


def test_catalogue_lookup_returns_raw_values_and_snapshot_provenance(tmp_path: Path) -> None:
    tool, raw_sha = make_catalogue_tool(tmp_path)
    result = tool.execute(
        ToolRequest(
            "catalogue-call",
            "catalogue.lookup",
            {
                "filters": {"pl_name": "Planet A"},
                "fields": ["pl_name", "pl_orbper"],
            },
        )
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.data["matched_count"] == 1
    assert result.data["snapshot_id"] == f"PSCompPars::{raw_sha}"
    assert len(result.evidence) == 1
    item = result.evidence[0]
    assert json.loads(item.excerpt) == {"pl_name": "Planet A", "pl_orbper": "12.500000"}
    assert item.record_id == f"PSCompPars::{raw_sha}::Planet A"
    assert item.snapshot_id == f"PSCompPars::{raw_sha}"
    assert item.source_uri == "https://paper.test/planet-a"
    assert item.metadata["raw_values_preserved"] is True
    assert item.metadata["source_row_number"] == 2


def test_catalogue_lookup_supports_contains_and_multiple_filters(tmp_path: Path) -> None:
    tool, _ = make_catalogue_tool(tmp_path)
    result = tool.execute(
        ToolRequest(
            "catalogue-call",
            "catalogue.lookup",
            {
                "filters": {"pl_name": "Planet", "hostname": "star b"},
                "fields": ["pl_name", "hostname", "pl_rade"],
                "match_mode": "contains",
            },
        )
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.data["matched_count"] == 1
    assert json.loads(result.evidence[0].excerpt) == {
        "pl_name": "Planet B",
        "hostname": "Star B",
        "pl_rade": "2.10",
    }


def test_catalogue_lookup_returns_successful_empty_result_when_no_row_matches(tmp_path: Path) -> None:
    tool, _ = make_catalogue_tool(tmp_path)
    result = tool.execute(
        ToolRequest(
            "catalogue-call",
            "catalogue.lookup",
            {"filters": {"pl_name": "Missing Planet"}, "fields": ["pl_name"]},
        )
    )

    assert result.status is ToolStatus.SUCCEEDED
    assert result.evidence == ()
    assert result.data["matched_count"] == 0
    assert "No catalogue rows" in (result.message or "")



def test_catalogue_lookup_marks_return_limit_as_partial(tmp_path: Path) -> None:
    tool, _ = make_catalogue_tool(tmp_path)
    result = tool.execute(
        ToolRequest(
            "call-1",
            "catalogue.lookup",
            {
                "filters": {"pl_name": "Planet"},
                "fields": ["pl_name"],
                "match_mode": "contains",
                "limit": 1,
            },
        )
    )

    assert result.status is ToolStatus.PARTIAL
    assert result.data["matched_count"] == 2
    assert result.data["returned_count"] == 1
    assert result.data["truncated"] is True

def test_catalogue_lookup_rejects_unknown_columns_and_blank_filters(tmp_path: Path) -> None:
    tool, _ = make_catalogue_tool(tmp_path)
    unknown_column = tool.execute(
        ToolRequest(
            "call-1",
            "catalogue.lookup",
            {"filters": {"not_a_column": "x"}, "fields": ["pl_name"]},
        )
    )
    blank_filter = tool.execute(
        ToolRequest(
            "call-2",
            "catalogue.lookup",
            {"filters": {"pl_name": " "}, "fields": ["pl_name"]},
        )
    )

    assert unknown_column.status is ToolStatus.FAILED
    assert "Unknown catalogue filter column" in (unknown_column.message or "")
    assert blank_filter.status is ToolStatus.FAILED
    assert "cannot be blank" in (blank_filter.message or "")


def test_catalogue_lookup_requires_explicit_nonempty_fields(tmp_path: Path) -> None:
    tool, _ = make_catalogue_tool(tmp_path)
    result = tool.execute(
        ToolRequest(
            "call-1",
            "catalogue.lookup",
            {"filters": {"pl_name": "Planet A"}, "fields": []},
        )
    )

    assert result.status is ToolStatus.FAILED
    assert result.error_code == "invalid_lookup_request"


def test_catalogue_lookup_detects_processed_csv_checksum_mismatch(tmp_path: Path) -> None:
    catalogue_path, report_path, _ = build_catalogue_files(tmp_path)
    catalogue_path.write_text(catalogue_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum does not match"):
        CatalogueRecordLookupTool(
            config=CatalogueLookupConfig(
                catalogue_path=catalogue_path,
                validation_report_path=report_path,
            )
        )


def test_catalogue_lookup_enforces_configurable_maximum_result_limit(tmp_path: Path) -> None:
    tool, _ = make_catalogue_tool(tmp_path, max_limit=2)
    result = tool.execute(
        ToolRequest(
            "call-1",
            "catalogue.lookup",
            {
                "filters": {"pl_name": "Planet"},
                "fields": ["pl_name"],
                "match_mode": "contains",
                "limit": 3,
            },
        )
    )

    assert result.status is ToolStatus.FAILED
    assert "limit must be between 1 and 2" in (result.message or "")
