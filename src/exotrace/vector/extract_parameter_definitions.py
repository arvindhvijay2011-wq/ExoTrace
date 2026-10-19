"""Extract NASA's published parameter definitions from the frozen source HTML.

No scientific definition text or field aliases are manually authored here. Definitions,
labels, descriptions, uncertainty associations, limit columns, and table membership are
parsed from NASA's frozen HTML source. Some uncertainty/limit field cards are generated
mechanically from relationships explicitly stated in the official table row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
from bs4 import BeautifulSoup

from exotrace.graph.build_graph import load_snapshot_bundle

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_MANIFEST_PATH = Path("data/manifests/reference_pages_manifest.json")
PROCESSED_HTML_FALLBACK = Path("data/raw/archive_parameter_columns.html")
OUTPUT_JSONL = Path("data/processed/parameter_definitions.jsonl")
OUTPUT_MANIFEST = Path("data/manifests/parameter_definitions_manifest.json")
SOURCE_SLUG = "archive_parameter_columns"
FIELD_RE = re.compile(r"^[\s()+-]*([A-Za-z][A-Za-z0-9_]*)[†‡*\s]*$")
UNCERTAINTY_RE = re.compile(r"\(\s*(\+|-)\s*\)\s*([A-Za-z][A-Za-z0-9_]*)")
TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*\b")
APPROVED_HOSTS = {"exoplanetarchive.ipac.caltech.edu", "exoplanetarchive.nexsci.services"}


def sha256_bytes(content: bytes) -> str:
    """Return SHA-256 checksum for bytes."""
    return hashlib.sha256(content).hexdigest()


def _clean_text(value: str) -> str:
    """Normalize HTML whitespace without paraphrasing the source wording."""
    return " ".join(value.replace("\xa0", " ").split())


def _field_name(value: str) -> str | None:
    """Return a likely database column name from the first source-table cell."""
    cleaned = _clean_text(value).replace("†", "").replace("‡", "").strip()
    match = FIELD_RE.fullmatch(cleaned)
    return match.group(1) if match else None


def _header_indices(header_cells: list[str]) -> dict[str, int] | None:
    """Identify the official definitions table columns using their header text."""
    lowered = [re.sub(r"\s+", " ", text).casefold() for text in header_cells]
    database_index = next((i for i, text in enumerate(lowered) if "database column name" in text), None)
    label_index = next((i for i, text in enumerate(lowered) if "table label" in text), None)
    description_index = next((i for i, text in enumerate(lowered) if "description" in text), None)
    if database_index is None or label_index is None or description_index is None:
        return None

    indices: dict[str, int] = {
        "field": database_index,
        "label": label_index,
        "description": description_index,
    }
    for key, needles in {
        "uncertainties": ("uncertainties column", "uncertainty column"),
        "limit": ("limit column",),
        "in_ps": ("in ps table",),
        "in_pscomppars": ("in pscomppars table", "in pscomp pars table"),
    }.items():
        found = next((i for i, text in enumerate(lowered) if any(n in text for n in needles)), None)
        if found is not None:
            indices[key] = found
    return indices


def _header_and_table_context(table: Any) -> tuple[dict[str, int], Any] | None:
    """Find a matching header row within an HTML table."""
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        texts = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]
        indices = _header_indices(texts)
        if indices:
            return indices, row
    return None


def _parse_source_rows(
    html: str,
    source_url: str,
    raw_sha256: str,
    expected_fields: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Parse parameter rows from NASA's actual published definitions tables."""
    soup = BeautifulSoup(html, "html.parser")
    parsed_rows: list[dict[str, Any]] = []
    seen_fields: set[str] = set()

    # First pass: use the actual source-row layout confirmed by the frozen NASA
    # HTML diagnostics. NASA's definitions table places the database field,
    # label, and description in the first three body cells. Some table-level
    # header structures contain grouped/row-spanned columns that make the
    # nominal header indexes incompatible with the body rows. Do not let those
    # header indexes prevent us from extracting an explicit source row.
    # Iterate over every parsed row in the document, not only rows that
    # BeautifulSoup attaches beneath a <table>. The frozen NASA HTML contains
    # continuation rows that BeautifulSoup exposes via soup.find_all("tr") but
    # does not retain as descendants of a table element. A table-descendant-only
    # traversal silently misses those legitimate source rows.
    for row in soup.find_all("tr"):
        table = row.find_parent("table")
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 3:
            continue
        texts = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]
        field = _field_name(texts[0])
        if not field or (expected_fields is not None and field not in expected_fields):
            continue
        if field in seen_fields or "_" not in field:
            continue

        label = texts[1].strip()
        description = texts[2].strip()
        if not label and not description:
            continue

        uncertainty_text = texts[3].strip() if len(texts) > 3 else ""
        uncertainty_fields = [
            {"polarity": "positive" if sign == "+" else "negative", "field": related}
            for sign, related in UNCERTAINTY_RE.findall(uncertainty_text)
        ]
        unique_associations: list[dict[str, str]] = []
        association_keys: set[tuple[str, str]] = set()
        for association in uncertainty_fields:
            key = (association["polarity"], association["field"])
            if key not in association_keys:
                unique_associations.append(association)
                association_keys.add(key)

        limit_text = texts[4].strip() if len(texts) > 4 else ""
        limit_field = next(
            (token for token in TOKEN_RE.findall(limit_text) if token.casefold().endswith("lim")),
            None,
        )
        in_ps_text = texts[5].strip().casefold() if len(texts) > 5 else ""
        in_composite_text = texts[6].strip().casefold() if len(texts) > 6 else ""
        context_node = table if table is not None else row
        previous_heading = context_node.find_previous(re.compile(r"^h[1-6]$"))
        table_section = (
            _clean_text(previous_heading.get_text(" ", strip=True))
            if previous_heading is not None
            else "Data Column Definitions"
        )

        parsed_rows.append(
            {
                "field": field,
                "label": label,
                "description": description,
                "uncertainty_fields": unique_associations,
                "uncertainty_source_text": uncertainty_text,
                "limit_field": limit_field,
                "limit_source_text": limit_text,
                "in_ps": True if in_ps_text == "x" else False if in_ps_text == "" else None,
                "in_pscomppars": (
                    True if in_composite_text == "x" else False if in_composite_text == "" else None
                ),
                "table_section": table_section,
                "source_url": source_url,
                "source_html_sha256": raw_sha256,
                "parse_method": "source_row_first_cell",
            }
        )
        seen_fields.add(field)

    # Fallback pass for source sections whose fields do not appear in the first
    # cell. Header-mapped parsing remains available, but cannot overwrite a
    # definition already extracted from an explicit source row.
    for table in soup.find_all("table"):
        header_context = _header_and_table_context(table)
        if header_context is None:
            continue
        indices, header_row = header_context
        header_found = False
        for row in table.find_all("tr"):
            if row is header_row:
                header_found = True
                continue
            if not header_found:
                continue
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            texts = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]
            max_index = max(indices[key] for key in ("field", "label", "description"))
            if len(texts) <= max_index:
                continue
            field = _field_name(texts[indices["field"]])
            label = texts[indices["label"]].strip()
            description = texts[indices["description"]].strip()
            if not field or (not label and not description):
                continue
            if field in seen_fields:
                # The source page may list the same field in default and category tables.
                # Keep the first actual definition, preserving source order.
                continue
            seen_fields.add(field)

            def cell_at(key: str) -> str:
                index = indices.get(key)
                return texts[index].strip() if index is not None and index < len(texts) else ""

            uncertainty_text = cell_at("uncertainties")
            if not uncertainty_text:
                uncertainty_text = " ".join(texts)
            uncertainty_fields = [
                {"polarity": "positive" if sign == "+" else "negative", "field": related}
                for sign, related in UNCERTAINTY_RE.findall(uncertainty_text)
            ]
            # Keep only distinct associations in their source order.
            unique_associations: list[dict[str, str]] = []
            association_keys: set[tuple[str, str]] = set()
            for association in uncertainty_fields:
                key = (association["polarity"], association["field"])
                if key not in association_keys:
                    unique_associations.append(association)
                    association_keys.add(key)

            limit_text = cell_at("limit")
            limit_tokens = TOKEN_RE.findall(limit_text)
            limit_field = next(
                (token for token in limit_tokens if token.casefold().endswith("lim")), None
            )
            in_ps_text = cell_at("in_ps").strip().casefold()
            in_composite_text = cell_at("in_pscomppars").strip().casefold()
            previous_heading = table.find_previous(re.compile(r"^h[1-6]$"))
            table_section = (
                _clean_text(previous_heading.get_text(" ", strip=True))
                if previous_heading is not None
                else "Data Column Definitions"
            )

            parsed_rows.append(
                {
                    "field": field,
                    "label": label,
                    "description": description,
                    "uncertainty_fields": unique_associations,
                    "uncertainty_source_text": uncertainty_text,
                    "limit_field": limit_field,
                    "limit_source_text": limit_text,
                    "in_ps": True if in_ps_text == "x" else False if in_ps_text == "" else None,
                    "in_pscomppars": (
                        True if in_composite_text == "x" else False if in_composite_text == "" else None
                    ),
                    "table_section": table_section,
                    "source_url": source_url,
                    "source_html_sha256": raw_sha256,
                    "parse_method": "header_mapped",
                }
            )

    # Fallback for NASA page sections whose HTML separates or fragments table headers.
    # We still extract the field label/description from the original row itself; no
    # definition text is authored or substituted by this fallback.
    recovered_fields: list[str] = []
    parsed_row_fields = {row["field"] for row in parsed_rows}
    for table in soup.find_all("table"):
        header_context = _header_and_table_context(table)
        header_indices = header_context[0] if header_context else {}
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) < 3:
                continue
            texts = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]
            # The primary parser can identify a header whose cell positions do not
            # align with the body rows (for example, grouped/continued NASA schema
            # tables with colspan/rowspan headers). In this recovery path we therefore
            # do not reuse header-derived indices. The source row diagnostics confirm
            # the database field is the first cell, followed by the label and verbatim
            # description, then uncertainty, limit, and table-availability cells.
            # Candidate rows are accepted only when that first cell matches a column
            # in the frozen validated dataset, reducing the risk of parsing unrelated
            # tables or confusing a limit/uncertainty column with a parameter row.
            field_index = 0
            field = _field_name(texts[field_index])
            if not field or (expected_fields is not None and field not in expected_fields):
                continue
            if field in parsed_row_fields or "_" not in field:
                continue

            # Preserve the positional order of the source row itself. This fallback
            # uses source cells verbatim and does not author missing definitions.
            label_index = field_index + 1
            description_index = field_index + 2
            if label_index >= len(texts) or description_index >= len(texts):
                continue
            label = texts[label_index].strip()
            description = texts[description_index].strip()
            if not label and not description:
                continue

            def fallback_cell_at(key: str, offset: int) -> str:
                # In this recovery path, use source row positions, not the potentially
                # misaligned grouped header map that caused the original extraction gap.
                index = field_index + offset
                return texts[index].strip() if 0 <= index < len(texts) else ""

            uncertainty_text = fallback_cell_at("uncertainties", 3)
            if not uncertainty_text:
                uncertainty_text = " ".join(texts[field_index + 3 :])
            uncertainty_fields = [
                {"polarity": "positive" if sign == "+" else "negative", "field": related}
                for sign, related in UNCERTAINTY_RE.findall(uncertainty_text)
            ]
            unique_associations: list[dict[str, str]] = []
            association_keys: set[tuple[str, str]] = set()
            for association in uncertainty_fields:
                key = (association["polarity"], association["field"])
                if key not in association_keys:
                    unique_associations.append(association)
                    association_keys.add(key)

            limit_text = fallback_cell_at("limit", 4)
            limit_tokens = TOKEN_RE.findall(limit_text)
            limit_field = next(
                (token for token in limit_tokens if token.casefold().endswith("lim")), None
            )
            in_ps_text = fallback_cell_at("in_ps", 5).casefold()
            in_composite_text = fallback_cell_at("in_pscomppars", 6).casefold()
            previous_heading = table.find_previous(re.compile(r"^h[1-6]$"))
            table_section = (
                _clean_text(previous_heading.get_text(" ", strip=True))
                if previous_heading is not None
                else "Data Column Definitions"
            )
            parsed_rows.append(
                {
                    "field": field,
                    "label": label,
                    "description": description,
                    "uncertainty_fields": unique_associations,
                    "uncertainty_source_text": uncertainty_text,
                    "limit_field": limit_field,
                    "limit_source_text": limit_text,
                    "in_ps": True if in_ps_text == "x" else False if in_ps_text == "" else None,
                    "in_pscomppars": True if in_composite_text == "x" else False if in_composite_text == "" else None,
                    "table_section": table_section,
                    "source_url": source_url,
                    "source_html_sha256": raw_sha256,
                    "parse_method": "positional_row_fallback",
                }
            )
            parsed_row_fields.add(field)
            recovered_fields.append(field)

    if not parsed_rows:
        raise ValueError(
            "No definitions were extracted from the frozen NASA HTML. The page markup may have "
            "changed; inspect the saved source rather than substituting hand-written definitions."
        )
    return parsed_rows


def _build_document(row: dict[str, Any], *, extraction_kind: str = "official_table_row") -> dict[str, Any]:
    """Build an atomic search document from a parsed NASA row or declared association."""
    field = str(row["field"])
    source_slug = SOURCE_SLUG
    source_url = str(row["source_url"])
    if extraction_kind == "official_table_row":
        text_parts = [
            f"NASA Exoplanet Archive database column: {field}.",
            f"Table label (source text): {row['label']}.",
        ]
        description = str(row.get("description") or "").strip()
        if description:
            text_parts.append(f"Description (verbatim from source): {description}")
        if row.get("uncertainty_fields"):
            uncertainty_text = "; ".join(
                f"{item['field']} ({item['polarity']} uncertainty)"
                for item in row["uncertainty_fields"]
            )
            text_parts.append(f"Associated uncertainty columns (parsed from source table): {uncertainty_text}.")
        if row.get("limit_field"):
            text_parts.append(f"Associated limit column (parsed from source table): {row['limit_field']}.")
        text_parts.append(f"Source table section: {row.get('table_section', 'Data Column Definitions')}.")
        metadata = {
            "parameter_field": field,
            "table_label": row["label"],
            "description_verbatim": description,
            "definition_extraction": extraction_kind,
            "table_section": row.get("table_section"),
            "uncertainty_fields": row.get("uncertainty_fields", []),
            "limit_field": row.get("limit_field"),
            "in_ps": row.get("in_ps"),
            "in_pscomppars": row.get("in_pscomppars"),
            "source_raw_sha256": row["source_html_sha256"],
            "source_row_parse_method": row.get("parse_method", "header_mapped"),
        }
        title = f"{row['label']} ({field})"
    else:
        parent = row["parent"]
        polarity = row["polarity"]
        relation_name = "positive (upper) uncertainty" if polarity == "positive" else "negative (lower) uncertainty"
        text_parts = [
            f"NASA Exoplanet Archive database column: {field}.",
            f"Role inferred from official table association: {relation_name} column for "
            f"{parent['label']} ({parent['field']}).",
            f"The source table's uncertainty cell associates this field with {parent['field']}; "
            "this role statement is generated mechanically from the published row, not copied as a separate field description.",
            f"Parent parameter description (verbatim from source): {parent['description']}",
            f"Source table section: {parent.get('table_section', 'Data Column Definitions')}.",
        ]
        metadata = {
            "parameter_field": field,
            "table_label": f"{parent['label']} {relation_name}",
            "definition_extraction": "derived_from_official_uncertainty_association",
            "related_parameter_field": parent["field"],
            "uncertainty_polarity": polarity,
            "parent_description_verbatim": parent["description"],
            "source_raw_sha256": parent["source_html_sha256"],
        }
        title = f"{parent['label']} {relation_name} ({field})"

    text_parts.append(f"Official source URL: {source_url}.")
    doc_id = f"reference:{source_slug}:chunk:field_{field}"
    return {
        "doc_id": doc_id,
        "doc_type": "official_nasa_parameter_definition",
        "title": title,
        "text": "\n".join(text_parts),
        "metadata": {
            "source_slug": source_slug,
            "source_url": source_url,
            "publisher": urlparse(source_url).hostname,
            "source_type": "official_nasa_parameter_definition",
            **metadata,
        },
    }


def extract_parameter_definitions() -> dict[str, Any]:
    """Extract source-backed definition documents for columns in the frozen dataset."""
    manifest_path = PROJECT_ROOT / REFERENCE_MANIFEST_PATH
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Reference manifest not found: {manifest_path}. Run "
            "`python -m exotrace.vector.fetch_reference_docs` first."
        )
    reference_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    page_manifest = next(
        (page for page in reference_manifest.get("pages", []) if page.get("slug") == SOURCE_SLUG),
        None,
    )
    if not page_manifest or page_manifest.get("status") != "downloaded":
        raise ValueError(f"The frozen reference manifest lacks a successful {SOURCE_SLUG!r} page.")

    source_url = str(page_manifest.get("url") or "")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in APPROVED_HOSTS:
        raise ValueError(f"Unapproved NASA source URL in manifest: {source_url!r}")

    raw_file = str(page_manifest.get("raw_file") or PROCESSED_HTML_FALLBACK.as_posix())
    raw_path = PROJECT_ROOT / raw_file
    if not raw_path.is_file():
        raise FileNotFoundError(
            f"Frozen source HTML not found: {raw_path}. The extractor requires the captured official HTML; "
            "it will not invent or manually substitute definitions."
        )
    raw_bytes = raw_path.read_bytes()
    actual_sha = sha256_bytes(raw_bytes)
    expected_sha = str(page_manifest.get("raw_sha256") or "")
    if not expected_sha or actual_sha != expected_sha:
        raise ValueError(
            f"Frozen NASA source HTML checksum mismatch for {raw_path}. Expected {expected_sha}, "
            f"got {actual_sha}. Re-capture deliberately with --refresh only if you intend to "
            "replace the source snapshot."
        )

    bundle = load_snapshot_bundle(PROJECT_ROOT)
    expected_fields = set(str(column) for column in bundle.dataframe.columns)
    extracted_rows = _parse_source_rows(
        raw_bytes.decode("utf-8", errors="replace"),
        source_url,
        actual_sha,
        expected_fields=expected_fields,
    )
    source_rows_by_field = {row["field"]: row for row in extracted_rows}

    docs_by_field: dict[str, dict[str, Any]] = {}
    for field, row in source_rows_by_field.items():
        if field in expected_fields:
            docs_by_field[field] = _build_document(row)

    derived_associations: list[dict[str, Any]] = []
    for parent in extracted_rows:
        for association in parent.get("uncertainty_fields", []):
            field = association["field"]
            if field in expected_fields and field not in docs_by_field:
                derived_associations.append({"field": field, "parent": parent, "polarity": association["polarity"]})
        limit_field = parent.get("limit_field")
        if limit_field and limit_field in expected_fields and limit_field not in docs_by_field:
            derived_associations.append({"field": limit_field, "parent": parent, "polarity": "limit"})

    for association in derived_associations:
        field = association["field"]
        if field in docs_by_field:
            continue
        parent = association["parent"]
        if association["polarity"] == "limit":
            role = {
                "field": field,
                "parent": parent,
                "polarity": "limit",
                "source_url": source_url,
            }
            doc = _build_limit_document(role)
        else:
            doc = _build_document({**association, "source_url": source_url}, extraction_kind="derived_association")
        docs_by_field[field] = doc

    core_fields = {"pl_orbeccen", "pl_orbper", "pl_insol"}.intersection(expected_fields)
    missing_core = sorted(core_fields - docs_by_field.keys())
    if missing_core:
        soup = BeautifulSoup(raw_bytes.decode("utf-8", errors="replace"), "html.parser")
        row_diagnostics: dict[str, list[list[str]]] = {}
        for field in missing_core:
            candidates: list[list[str]] = []
            for row in soup.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                texts = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]
                if any(field in value for value in texts):
                    candidates.append(texts[:8])
            row_diagnostics[field] = candidates[:3]
        raise ValueError(
            "The NASA schema parser failed to extract core parameter fields: "
            f"{missing_core}. Source-row diagnostics (original cell text): "
            f"{json.dumps(row_diagnostics, ensure_ascii=False)}. "
            "Inspect the frozen source HTML; do not add manual cards."
        )

    ordered_docs = [docs_by_field[field] for field in bundle.dataframe.columns if field in docs_by_field]
    extracted_fields = set(docs_by_field)
    unmatched_fields = [field for field in bundle.dataframe.columns if field not in extracted_fields]
    if not ordered_docs:
        raise ValueError("No dataset field definitions matched the frozen NASA schema.")
    coverage = len(extracted_fields) / len(expected_fields) if expected_fields else 1.0
    parse_method_counts: dict[str, int] = {}
    for row in extracted_rows:
        method = str(row.get("parse_method", "header_mapped"))
        parse_method_counts[method] = parse_method_counts.get(method, 0) + 1
    if coverage < 0.75:
        raise ValueError(
            f"Only {coverage:.1%} of validated dataset columns matched the frozen NASA schema. "
            "Stop and inspect the source markup/parser before building the retrieval corpus."
        )

    output_path = PROJECT_ROOT / OUTPUT_JSONL
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = "".join(
        json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for doc in ordered_docs
    )
    temporary = output_path.with_suffix(".jsonl.tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(output_path)
    output_sha = sha256_bytes(output_path.read_bytes())

    manifest = {
        "project": "ExoTrace",
        "extracted_at_utc": datetime.now(UTC).isoformat(),
        "extraction_policy": (
            "Definitions, labels, descriptions, uncertainty associations, limit fields, and table "
            "availability are parsed from the frozen official NASA HTML. Uncertainty/limit cards "
            "without separate source rows are generated only from explicitly documented table associations."
        ),
        "source_slug": SOURCE_SLUG,
        "source_url": source_url,
        "source_raw_file": raw_file,
        "source_raw_sha256": actual_sha,
        "source_retrieved_at_utc": reference_manifest.get("retrieved_at_utc"),
        "reference_manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        "catalogue_snapshot_id": bundle.snapshot_id,
        "catalogue_source_sha256": bundle.source_sha256,
        "dataset_column_count": len(bundle.dataframe.columns),
        "dataset_columns": list(bundle.dataframe.columns),
        "source_rows_parsed": len(extracted_rows),
        "source_row_parse_method_counts": parse_method_counts,
        "definition_document_count": len(ordered_docs),
        "matched_dataset_columns": sorted(extracted_fields),
        "unmatched_dataset_columns": unmatched_fields,
        "matched_column_coverage": round(len(extracted_fields) / len(expected_fields), 4) if expected_fields else 1.0,
        "output_jsonl": OUTPUT_JSONL.as_posix(),
        "output_jsonl_sha256": output_sha,
        "manual_glossary_used": False,
    }
    (PROJECT_ROOT / OUTPUT_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Frozen NASA source: {raw_file}")
    print(f"Source rows parsed: {len(extracted_rows)}")
    print(f"Row parsing methods: {json.dumps(parse_method_counts, sort_keys=True)}")
    print(f"Validated dataset columns: {len(expected_fields)}")
    print(f"Definition documents extracted: {len(ordered_docs)}")
    print(f"Dataset column coverage: {manifest['matched_column_coverage']:.1%}")
    if unmatched_fields:
        print("Dataset columns without a matched source row/association:")
        print("  " + ", ".join(unmatched_fields))
    print(f"Manual glossary used: {manifest['manual_glossary_used']}")
    print(f"Definitions: {OUTPUT_JSONL.as_posix()}")
    print(f"Manifest: {OUTPUT_MANIFEST.as_posix()}")
    print(f"Definitions SHA-256: {output_sha}")
    return manifest


def _build_limit_document(association: dict[str, Any]) -> dict[str, Any]:
    """Create a mechanical document for a limit column linked by the source table."""
    field = association["field"]
    parent = association["parent"]
    source_url = association["source_url"]
    role = f"limit-column association for {parent['label']} ({parent['field']})"
    text = "\n".join(
        [
            f"NASA Exoplanet Archive database column: {field}.",
            f"Role inferred from official table association: {role}.",
            f"The NASA definition table lists {field} as the limit column for {parent['field']}.",
            f"Parent parameter description (verbatim from source): {parent['description']}",
            f"Official source URL: {source_url}.",
        ]
    )
    return {
        "doc_id": f"reference:{SOURCE_SLUG}:chunk:field_{field}",
        "doc_type": "official_nasa_parameter_definition",
        "title": f"{parent['label']} limit column ({field})",
        "text": text,
        "metadata": {
            "source_slug": SOURCE_SLUG,
            "source_url": source_url,
            "publisher": urlparse(source_url).hostname,
            "source_type": "official_nasa_parameter_definition",
            "parameter_field": field,
            "table_label": f"{parent['label']} limit column",
            "definition_extraction": "derived_from_official_limit_association",
            "related_parameter_field": parent["field"],
            "parent_description_verbatim": parent["description"],
            "source_raw_sha256": parent["source_html_sha256"],
        },
    }


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-unmatched",
        action="store_true",
        help="Print dataset columns that have no matching NASA schema definition or association.",
    )
    args = parser.parse_args()
    try:
        manifest = extract_parameter_definitions()
        if args.show_unmatched:
            print(json.dumps(manifest["unmatched_dataset_columns"], indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
