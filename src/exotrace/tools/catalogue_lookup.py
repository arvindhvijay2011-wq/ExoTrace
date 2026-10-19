"""Validated, read-only lookup over ExoTrace's frozen NASA PSCompPars snapshot."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from exotrace.contracts import EvidenceReference
from exotrace.tools.contracts import ToolDescriptor, ToolRequest, ToolResult, ToolStatus

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOGUE_PATH = PROJECT_ROOT / "data" / "processed" / "planets_validated.csv"
DEFAULT_VALIDATION_REPORT_PATH = PROJECT_ROOT / "data" / "manifests" / "validation_report.json"
REQUIRED_IDENTITY_COLUMNS = ("pl_name", "hostname")


@dataclass(frozen=True, slots=True)
class CatalogueLookupConfig:
    """Paths and resource limits for catalogue lookups.

    Limits are configurable operational safeguards. The data values, available fields, and
    snapshot identity are always derived from the validated files and their manifest.
    """

    catalogue_path: Path = field(default_factory=lambda: DEFAULT_CATALOGUE_PATH)
    validation_report_path: Path = field(default_factory=lambda: DEFAULT_VALIDATION_REPORT_PATH)
    default_limit: int = 10
    max_limit: int = 100
    case_sensitive: bool = False
    require_validation_report: bool = True

    def __post_init__(self) -> None:
        """Normalize paths and validate lookup limits."""
        object.__setattr__(self, "catalogue_path", Path(self.catalogue_path))
        object.__setattr__(self, "validation_report_path", Path(self.validation_report_path))
        if isinstance(self.default_limit, bool) or not isinstance(self.default_limit, int):
            raise TypeError("default_limit must be an integer.")
        if isinstance(self.max_limit, bool) or not isinstance(self.max_limit, int):
            raise TypeError("max_limit must be an integer.")
        if self.default_limit < 1:
            raise ValueError("default_limit must be at least 1.")
        if self.max_limit < self.default_limit:
            raise ValueError("max_limit must be at least default_limit.")
        if not isinstance(self.case_sensitive, bool):
            raise TypeError("case_sensitive must be a boolean.")
        if not isinstance(self.require_validation_report, bool):
            raise TypeError("require_validation_report must be a boolean.")


@dataclass(frozen=True, slots=True)
class _CatalogueRow:
    """One preserved CSV record and its physical source line number."""

    source_line_number: int
    values: Mapping[str, str | None]


class CatalogueRecordLookupTool:
    """Retrieve exact or substring-matched rows and preserve raw field values.

    The lookup accepts structured column filters supplied by its caller. It does not parse
    natural-language questions, infer which planet the user meant, calculate measurements,
    or execute arbitrary queries against Neo4j.
    """

    TOOL_ID = "catalogue.lookup"

    def __init__(self, *, config: CatalogueLookupConfig | None = None) -> None:
        """Load and verify the validated snapshot once for stable, repeatable lookups."""
        self._config = config or CatalogueLookupConfig()
        self._rows: tuple[_CatalogueRow, ...]
        self._columns: tuple[str, ...]
        self._manifest: dict[str, Any]
        self._catalogue_sha256: str
        self._snapshot_id: str | None
        self._source_file: str
        self._load_snapshot()

    @property
    def descriptor(self) -> ToolDescriptor:
        """Expose the bounded lookup interface to eligible specialist agents."""
        return ToolDescriptor(
            tool_id=self.TOOL_ID,
            name="Validated catalogue record lookup",
            purpose=(
                "Retrieve raw field values from the validated, manifest-checked NASA "
                "PSCompPars snapshot using structured column filters. No writes or "
                "natural-language interpretation are performed."
            ),
            capabilities=("catalogue.lookup", "catalogue.raw_values", "source.provenance"),
            input_schema={
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "minProperties": 1,
                        "additionalProperties": {"type": "string"},
                    },
                    "fields": {
                        "type": "array",
                        "minItems": 1,
                        # Expose only columns present in the loaded, validated snapshot.
                        # This schema is generated from source data, never a static glossary.
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "enum": list(self._columns),
                        },
                        "uniqueItems": True,
                    },
                    "match_mode": {"type": "string", "enum": ["exact", "contains"]},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["filters", "fields"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "matched_count": {"type": "integer", "minimum": 0},
                    "returned_count": {"type": "integer", "minimum": 0},
                    "truncated": {"type": "boolean"},
                    "selected_fields": {"type": "array", "items": {"type": "string"}},
                    "snapshot_id": {"type": ["string", "null"]},
                    "catalogue_sha256": {"type": "string"},
                },
            },
            read_only=True,
        )

    @property
    def columns(self) -> tuple[str, ...]:
        """Return the source-defined column names for clients that need to construct tasks."""
        return self._columns

    @property
    def planet_host_identities(self) -> tuple[tuple[str, str], ...]:
        """Return canonical planet/host identifiers from the verified catalogue snapshot.

        Values are sourced from the CSV whose checksum and validation manifest were verified
        during initialization. This exposes only the two identity columns, not raw measurements.
        """
        identities: list[tuple[str, str]] = []
        for row in self._rows:
            planet_name = row.values.get("pl_name")
            hostname = row.values.get("hostname")
            if not planet_name or not hostname:
                # Snapshot loading already enforces these fields; fail closed if that invariant
                # is ever changed by a future implementation.
                raise RuntimeError("Validated catalogue contains an incomplete planet identity.")
            identities.append((planet_name, hostname))
        return tuple(identities)

    @property
    def snapshot_id(self) -> str | None:
        """Return the verified snapshot identifier, when present in the manifest."""
        return self._snapshot_id

    @property
    def catalogue_sha256(self) -> str:
        """Return the SHA-256 of the processed CSV loaded by this tool."""
        return self._catalogue_sha256

    def execute(self, request: ToolRequest) -> ToolResult:
        """Return records matching all supplied filters, without altering source values."""
        if request.tool_id != self.TOOL_ID:
            return self._failure(request, "wrong_tool_id", "Request tool ID does not match.")

        arguments = dict(request.arguments)
        unsupported = sorted(set(arguments) - {"filters", "fields", "match_mode", "limit"})
        if unsupported:
            return self._failure(
                request,
                "unsupported_arguments",
                f"Unsupported catalogue lookup arguments: {unsupported}.",
            )

        try:
            filters = self._validate_filters(arguments.get("filters"))
            fields = self._validate_fields(arguments.get("fields"))
            match_mode = arguments.get("match_mode", "exact")
            if match_mode not in {"exact", "contains"}:
                raise ValueError("match_mode must be either 'exact' or 'contains'.")
            limit = arguments.get("limit", self._config.default_limit)
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise ValueError("limit must be an integer.")
            if limit < 1 or limit > self._config.max_limit:
                raise ValueError(f"limit must be between 1 and {self._config.max_limit}.")
        except (TypeError, ValueError) as exc:
            return self._failure(request, "invalid_lookup_request", str(exc))

        matches = [
            row
            for row in self._rows
            if self._row_matches(row.values, filters=filters, match_mode=match_mode)
        ]
        selected_rows = matches[:limit]
        evidence: list[EvidenceReference] = []
        for row in selected_rows:
            evidence.append(self._evidence_for_row(row, fields=fields))

        truncated = len(matches) > len(selected_rows)
        status = ToolStatus.PARTIAL if truncated else ToolStatus.SUCCEEDED
        message = (
            f"Only {len(selected_rows)} of {len(matches)} matching records were returned "
            f"because the configured result limit is {limit}."
            if truncated
            else (
                "No catalogue rows matched the supplied filters."
                if not matches
                else None
            )
        )
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=status,
            data={
                "matched_count": len(matches),
                "returned_count": len(selected_rows),
                "truncated": truncated,
                "filters": filters,
                "match_mode": match_mode,
                "selected_fields": list(fields),
                "snapshot_id": self._snapshot_id,
                "catalogue_sha256": self._catalogue_sha256,
                "source_file": self._source_file,
            },
            evidence=tuple(evidence),
            message=message,
        )

    def _load_snapshot(self) -> None:
        """Read the manifest and CSV, verifying the exact processed-file checksum."""
        csv_path = self._config.catalogue_path
        report_path = self._config.validation_report_path
        if not csv_path.is_file():
            raise FileNotFoundError(f"Validated catalogue CSV does not exist: {csv_path}")

        report: dict[str, Any] = {}
        if report_path.is_file():
            try:
                loaded_report = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid validation report JSON: {report_path}") from exc
            if not isinstance(loaded_report, dict):
                raise ValueError("Validation report must contain a JSON object.")
            report = loaded_report
        elif self._config.require_validation_report:
            raise FileNotFoundError(f"Required validation report does not exist: {report_path}")

        if self._config.require_validation_report and report.get("passed") is not True:
            raise ValueError(
                "Catalogue validation report is missing or does not record passed=true."
            )

        file_bytes = csv_path.read_bytes()
        actual_sha256 = hashlib.sha256(file_bytes).hexdigest()
        expected_sha256 = report.get("processed_sha256")
        if expected_sha256:
            if not isinstance(expected_sha256, str) or expected_sha256.casefold() != actual_sha256:
                raise ValueError(
                    "Validated catalogue CSV checksum does not match validation_report.json."
                )
        elif self._config.require_validation_report:
            raise ValueError("Validation report does not include processed_sha256.")

        raw_sha256 = report.get("raw_sha256")
        self._snapshot_id = (
            f"PSCompPars::{raw_sha256}"
            if isinstance(raw_sha256, str) and raw_sha256.strip()
            else None
        )
        self._catalogue_sha256 = actual_sha256
        self._manifest = report
        self._source_file = str(report.get("processed_file") or csv_path.name)

        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("Validated catalogue CSV has no header row.")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("Validated catalogue CSV contains duplicate column names.")
            self._columns = tuple(reader.fieldnames)
            missing_identity_columns = sorted(set(REQUIRED_IDENTITY_COLUMNS) - set(self._columns))
            if missing_identity_columns:
                raise ValueError(
                    "Validated catalogue is missing required identity columns: "
                    + ", ".join(missing_identity_columns)
                )

            loaded_rows: list[_CatalogueRow] = []
            seen_planet_names: set[str] = set()
            for row in reader:
                if None in row:
                    raise ValueError(
                        f"CSV row near line {reader.line_num} contains more values than the header."
                    )
                normalized = {
                    column: self._clean_cell(value)
                    for column, value in row.items()
                    if column is not None
                }
                if all(value is None for value in normalized.values()):
                    continue
                planet_name = normalized.get("pl_name")
                hostname = normalized.get("hostname")
                if not planet_name or not hostname:
                    raise ValueError(
                        f"CSV row near line {reader.line_num} has a missing planet or host name."
                    )
                if planet_name in seen_planet_names:
                    raise ValueError(
                        "Validated catalogue contains duplicate planet names; record identity "
                        f"would be ambiguous: {planet_name!r}."
                    )
                seen_planet_names.add(planet_name)
                loaded_rows.append(
                    _CatalogueRow(source_line_number=reader.line_num, values=normalized)
                )

        expected_rows = report.get("row_count")
        if expected_rows is not None and int(expected_rows) != len(loaded_rows):
            raise ValueError(
                "Validated catalogue row count does not match validation_report.json."
            )
        if not loaded_rows:
            raise ValueError("Validated catalogue CSV contains no data rows.")
        self._rows = tuple(loaded_rows)

    @staticmethod
    def _clean_cell(value: str | None) -> str | None:
        """Normalize blank cells to None while preserving other source strings verbatim-ish."""
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None

    def _validate_filters(self, raw_filters: Any) -> dict[str, str]:
        """Validate filters against the actual columns in the loaded source file."""
        if not isinstance(raw_filters, Mapping) or not raw_filters:
            raise ValueError("filters must be a non-empty object of column-to-value pairs.")
        filters: dict[str, str] = {}
        for raw_column, raw_value in raw_filters.items():
            if not isinstance(raw_column, str) or not raw_column:
                raise ValueError("Every filter column must be a non-empty string.")
            if raw_column not in self._columns:
                raise ValueError(f"Unknown catalogue filter column: {raw_column!r}.")
            if isinstance(raw_value, bool) or not isinstance(raw_value, (str, int, float)):
                raise ValueError(f"Filter value for {raw_column!r} must be a string or number.")
            if isinstance(raw_value, float) and not math.isfinite(raw_value):
                raise ValueError(f"Filter value for {raw_column!r} must be finite.")
            value = str(raw_value).strip()
            if not value:
                raise ValueError(f"Filter value for {raw_column!r} cannot be blank.")
            filters[raw_column] = value
        return filters

    def _validate_fields(self, raw_fields: Any) -> tuple[str, ...]:
        """Validate the selected fields using the real source header, not a glossary."""
        if not isinstance(raw_fields, list) or not raw_fields:
            raise ValueError("fields must be a non-empty list of source column names.")
        if any(not isinstance(item, str) or not item.strip() for item in raw_fields):
            raise ValueError("fields must contain non-empty strings.")
        fields = tuple(item.strip() for item in raw_fields)
        if len(fields) != len(set(fields)):
            raise ValueError("fields cannot contain duplicates.")
        unknown_fields = sorted(set(fields) - set(self._columns))
        if unknown_fields:
            raise ValueError(f"Unknown catalogue fields: {unknown_fields}.")
        return fields

    def _row_matches(
        self,
        row: Mapping[str, str | None],
        *,
        filters: Mapping[str, str],
        match_mode: str,
    ) -> bool:
        """Match every filter deterministically without executing user-supplied code."""
        for column, expected in filters.items():
            actual_value = row.get(column)
            if actual_value is None:
                return False
            actual = actual_value if self._config.case_sensitive else actual_value.casefold()
            target = expected if self._config.case_sensitive else expected.casefold()
            if match_mode == "exact" and actual != target:
                return False
            if match_mode == "contains" and target not in actual:
                return False
        return True

    def _evidence_for_row(
        self,
        row: _CatalogueRow,
        *,
        fields: tuple[str, ...],
    ) -> EvidenceReference:
        """Build a source-linked evidence record without inferring scientific meaning."""
        values = {field_name: row.values[field_name] for field_name in fields}
        planet_name = row.values["pl_name"]
        hostname = row.values["hostname"]
        record_id = (
            f"{self._snapshot_id}::{planet_name}" if self._snapshot_id and planet_name else None
        )
        row_source_id = (
            record_id
            if record_id
            else f"processed-csv:{self._catalogue_sha256}:row:{row.source_line_number}"
        )
        evidence_id = f"catalogue:{row_source_id}"

        field_reference_links: dict[str, str] = {}
        for field_name in fields:
            reference_column = f"{field_name}_reflink"
            reference_value = row.values.get(reference_column)
            if reference_value:
                field_reference_links[field_name] = reference_value

        source_uri = next(
            (
                link
                for link in field_reference_links.values()
                if link.startswith(("https://", "http://")) and "<" not in link
            ),
            None,
        )
        excerpt = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
        return EvidenceReference(
            evidence_id=evidence_id,
            source_id=row_source_id,
            title=f"{planet_name} catalogue record",
            excerpt=excerpt,
            source_uri=source_uri,
            source_kind="NASA Exoplanet Archive PSCompPars catalogue record",
            snapshot_id=self._snapshot_id,
            record_id=record_id,
            metadata={
                "hostname": hostname,
                "source_table": "PSCompPars",
                "source_file": self._source_file,
                "source_row_number": row.source_line_number,
                "catalogue_sha256": self._catalogue_sha256,
                "snapshot_id": self._snapshot_id,
                "record_id": record_id,
                "selected_fields": list(fields),
                "field_reference_links": field_reference_links,
                "raw_values_preserved": True,
            },
        )

    @staticmethod
    def _failure(request: ToolRequest, code: str, message: str) -> ToolResult:
        """Return a structured failure for invalid lookup requests."""
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.FAILED,
            data={},
            message=message,
            error_code=code,
        )
