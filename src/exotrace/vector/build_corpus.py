"""Build a reproducible text corpus from frozen NASA pages and catalogue profiles.

Generated planet profiles improve textual discovery and entity resolution. They are
not independent scientific sources: numeric answers must still use authoritative
catalogue records and preserve uncertainty/missingness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import pandas as pd

from exotrace.graph.build_graph import classify_insolation, load_snapshot_bundle, to_neo4j_scalar

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_PAGES_JSONL = Path("data/processed/reference_pages.jsonl")
CORPUS_JSONL = Path("data/processed/vector_corpus.jsonl")
CORPUS_MANIFEST = Path("data/manifests/vector_corpus_manifest.json")
REFERENCE_MANIFEST = Path("data/manifests/reference_pages_manifest.json")
PARAMETER_DEFINITIONS_JSONL = Path("data/processed/parameter_definitions.jsonl")
PARAMETER_DEFINITIONS_MANIFEST = Path("data/manifests/parameter_definitions_manifest.json")
CHUNK_WORDS = 180
CHUNK_OVERLAP_WORDS = 30
REFERENCE_TARGET_WORDS = 150
REFERENCE_MAX_WORDS = 220
REFERENCE_CHUNKING_VERSION = "paragraph_section_v2"

REFERENCE_DISPLAY_TITLES: dict[str, str] = {
    "exoplanet_overview": "NASA Exoplanets Overview",
    "detection_methods": "How NASA Finds and Characterizes Exoplanets",
    "exoplanet_facts": "NASA Exoplanet Facts",
    "habitable_zone": "The Habitable Zone",
    "archive_parameter_columns": "NASA Exoplanet Archive Parameter Definitions",
    "composite_parameter_calculations": "NASA Exoplanet Archive Composite Parameter Calculations",
    "tap_query_documentation": "NASA Exoplanet Archive TAP Query Documentation",
}

PROFILE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("pl_orbper", "Orbital period", "days"),
    ("pl_orbsmax", "Orbital semi-major axis", "AU"),
    ("pl_rade", "Planet radius", "Earth radii"),
    ("pl_bmasse", "Planet mass", "Earth masses"),
    ("pl_eqt", "Equilibrium temperature", "K"),
    ("pl_orbeccen", "Orbital eccentricity", "dimensionless"),
    ("pl_insol", "Insolation relative to Earth", "Earth flux units"),
    ("st_teff", "Host-star effective temperature", "K"),
    ("st_rad", "Host-star radius", "Solar radii"),
    ("st_mass", "Host-star mass", "Solar masses"),
    ("sy_dist", "System distance", "parsecs"),
)


def sha256_bytes(content: bytes) -> str:
    """Return a lowercase SHA-256 checksum."""
    return hashlib.sha256(content).hexdigest()


def _json_line(record: dict[str, Any]) -> str:
    """Serialize JSON deterministically for stable checksums."""
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_missing(value: Any) -> bool:
    """Check pandas scalar missingness without treating zero as missing."""
    if value is None:
        return True
    try:
        missing = pd.isna(value)
        return bool(missing) if not hasattr(missing, "item") else bool(missing.item())
    except (TypeError, ValueError):
        return False


def format_value(value: Any) -> str | None:
    """Format source values compactly without inventing replacements."""
    if _is_missing(value):
        return None
    normalized = to_neo4j_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, float):
        return format(normalized, ".8g")
    return str(normalized)


def chunk_words(
    text: str,
    *,
    chunk_words: int = CHUNK_WORDS,
    overlap_words: int = CHUNK_OVERLAP_WORDS,
) -> list[str]:
    """Split a long reference page into overlapping word-window chunks."""
    if chunk_words < 1:
        raise ValueError("chunk_words must be at least 1.")
    if overlap_words < 0 or overlap_words >= chunk_words:
        raise ValueError("overlap_words must be in range [0, chunk_words).")
    words = text.split()
    if not words:
        return []
    stride = chunk_words - overlap_words
    chunks: list[str] = []
    for start in range(0, len(words), stride):
        chunk = " ".join(words[start : start + chunk_words]).strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


def _looks_like_heading(block: str) -> bool:
    """Heuristically identify short heading-like blocks from the frozen HTML text."""
    words = block.split()
    if not words or len(words) > 14 or len(block) > 115:
        return False
    # Short questions and label-like phrases are common NASA section headings.
    # Complete prose sentences are kept as content blocks.
    return not block.rstrip().endswith((".", "!", ";"))


def _split_long_reference_block(block: str, *, max_words: int) -> list[str]:
    """Split an unusually long paragraph while preferring sentence boundaries."""
    words = block.split()
    if len(words) <= max_words:
        return [block]

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘(])", block)
    if len(sentences) <= 1:
        return chunk_words(block, chunk_words=max_words, overlap_words=20)

    chunks: list[str] = []
    current: list[str] = []
    current_count = 0
    for sentence in sentences:
        sentence_words = sentence.split()
        if len(sentence_words) > max_words:
            if current:
                chunks.append(" ".join(current).strip())
                current = []
                current_count = 0
            chunks.extend(chunk_words(sentence, chunk_words=max_words, overlap_words=20))
            continue
        if current and current_count + len(sentence_words) > max_words:
            chunks.append(" ".join(current).strip())
            current = []
            current_count = 0
        current.append(sentence)
        current_count += len(sentence_words)
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def chunk_reference_text(
    text: str,
    *,
    page_title: str = "NASA reference",
    target_words: int = REFERENCE_TARGET_WORDS,
    max_words: int = REFERENCE_MAX_WORDS,
) -> list[dict[str, Any]]:
    """Create section-aware chunks while preserving blank-line paragraph boundaries.

    The frozen page exporter separates HTML headings and prose blocks with blank lines.
    This function uses those boundaries instead of flattening a whole page into arbitrary
    overlapping word windows. It returns each chunk's section heading and word count so
    retrieval results can be inspected and evaluated.
    """
    if target_words < 1 or max_words < target_words:
        raise ValueError("Require 1 <= target_words <= max_words.")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_blocks = [" ".join(part.split()) for part in re.split(r"\n\s*\n", normalized)]
    blocks = [block for block in raw_blocks if block]
    # Ignore a repeated generic browser title that was included in main-page content.
    cleaned_blocks: list[str] = []
    page_title_key = re.sub(r"\W+", " ", page_title).strip().casefold()
    for block in blocks:
        block_key = re.sub(r"\W+", " ", block).strip().casefold()
        if block_key == page_title_key:
            continue
        if block.casefold().endswith(" - nasa science") and len(block.split()) <= 7:
            continue
        cleaned_blocks.append(block)

    chunks: list[dict[str, Any]] = []
    current_heading = page_title
    current_blocks: list[str] = []
    current_word_count = 0

    def flush() -> None:
        nonlocal current_blocks, current_word_count
        if not current_blocks:
            return
        body = "\n\n".join(current_blocks).strip()
        chunks.append(
            {
                "section_heading": current_heading,
                "body": body,
                "word_count": len(body.split()),
            }
        )
        current_blocks = []
        current_word_count = 0

    for block in cleaned_blocks:
        if _looks_like_heading(block):
            flush()
            current_heading = block
            continue

        for unit in _split_long_reference_block(block, max_words=max_words):
            unit_word_count = len(unit.split())
            if current_blocks and current_word_count + unit_word_count > max_words:
                flush()
            current_blocks.append(unit)
            current_word_count += unit_word_count
            if current_word_count >= target_words:
                flush()

    flush()

    # Some pages may have content with no detectable headings. A page-level label is
    # still attached to those chunks; section_heading then equals page_title.
    return chunks


def _load_reference_pages(path: Path) -> list[dict[str, Any]]:
    """Load and validate the locally frozen explanatory page records."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Reference page text not found: {path}. Run "
            "`python -m exotrace.vector.fetch_reference_docs` first."
        )
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on {path}, line {line_number}: {exc}") from exc
        if not record.get("doc_id") or not record.get("url") or not record.get("text"):
            raise ValueError(
                f"Reference document on line {line_number} is missing ID, URL, or text."
            )
        parsed_url = urlparse(str(record["url"]))
        if parsed_url.scheme != "https" or parsed_url.hostname not in {
            "science.nasa.gov",
            "exoplanetarchive.ipac.caltech.edu",
        }:
            raise ValueError(
                f"Reference document on line {line_number} is not from an approved NASA host: "
                f"{record['url']}"
            )
        records.append(record)
    if not records:
        raise ValueError(f"No reference page records found in {path}.")
    return records


def _planet_profile(
    row: pd.Series,
    *,
    snapshot_id: str,
    source_file: str,
    source_sha256: str,
    source_row_number: int,
) -> dict[str, Any]:
    """Turn one catalogue row into a traceable text representation."""
    planet_name = format_value(row.get("pl_name"))
    host_name = format_value(row.get("hostname"))
    if not planet_name or not host_name:
        raise ValueError(f"Missing planet or host identity at CSV data row {source_row_number}.")

    record_id = f"{snapshot_id}::{planet_name}"
    profile_lines = [
        f"Exoplanet catalogue profile: {planet_name}.",
        f"Host star: {host_name}.",
    ]

    simple_fields: tuple[tuple[str, str], ...] = (
        ("discoverymethod", "Discovery method"),
        ("disc_year", "Discovery year"),
        ("disc_facility", "Discovery facility"),
        ("disc_telescope", "Discovery telescope"),
        ("disc_instrument", "Discovery instrument"),
        ("pl_bmassprov", "Planet mass provenance category"),
        ("st_spectype", "Host-star spectral type"),
    )
    for column, label in simple_fields:
        value = format_value(row.get(column))
        if value:
            profile_lines.append(f"{label}: {value}.")

    present_parameter_count = 0
    missing_parameter_labels: list[str] = []
    for column, label, unit in PROFILE_FIELDS:
        value = format_value(row.get(column))
        if value is None:
            missing_parameter_labels.append(label)
            continue
        present_parameter_count += 1
        line = f"{label}: {value} {unit}."
        err1_column = f"{column}err1"
        err2_column = f"{column}err2"
        upper_error = format_value(row.get(err1_column)) if err1_column in row.index else None
        lower_error = format_value(row.get(err2_column)) if err2_column in row.index else None
        if upper_error is not None or lower_error is not None:
            uncertainty_parts: list[str] = []
            if upper_error is not None:
                uncertainty_parts.append(f"upper error {upper_error} {unit}")
            if lower_error is not None:
                uncertainty_parts.append(f"lower error {lower_error} {unit}")
            line += " Reported uncertainty fields: " + "; ".join(uncertainty_parts) + "."
        profile_lines.append(line)

        limit_column = f"{column}lim"
        if limit_column in row.index:
            limit_value = format_value(row.get(limit_column))
            if limit_value is not None and limit_value != "0":
                profile_lines.append(f"Catalogue limit flag for {label}: {limit_value}.")

    insolation_status = classify_insolation(row.get("pl_insol"), row.get("pl_insol_reflink"))
    profile_lines.append(f"Insolation data-quality status: {insolation_status}.")
    if insolation_status in {"calculated_zero_requires_caution", "source_zero_requires_caution"}:
        profile_lines.append(
            "Caution: the catalogue value is exactly zero and is flagged for review; "
            "do not silently interpret it as a validated physical zero."
        )
    if missing_parameter_labels:
        profile_lines.append(
            "No value reported in this catalogue record for: "
            + ", ".join(missing_parameter_labels)
            + "."
        )

    discovery_reference = format_value(row.get("disc_refname"))
    if discovery_reference:
        profile_lines.append(
            "Discovery reference is recorded in the source catalogue; consult the linked "
            "CatalogueRecord for the original reference markup."
        )

    profile_lines.extend(
        [
            "Source table: NASA Exoplanet Archive PSCompPars.",
            f"Source snapshot ID: {snapshot_id}.",
            f"Catalogue record ID: {record_id}.",
            f"Source row number in the CSV, including the header as row 1: {source_row_number}.",
            f"Source file: {source_file}.",
            f"Source file SHA-256: {source_sha256}.",
            "This generated profile is a search aid, not an independent scientific publication. "
            "Use the original catalogue record for numerical answers, units, uncertainty fields, "
            "and provenance.",
        ]
    )

    source_doc_id = "planet:" + hashlib.sha256(record_id.encode("utf-8")).hexdigest()
    return {
        "doc_id": source_doc_id,
        "doc_type": "planet_profile",
        "title": f"Catalogue profile: {planet_name}",
        "text": "\n".join(profile_lines),
        "metadata": {
            "planet_name": planet_name,
            "hostname": host_name,
            "record_id": record_id,
            "snapshot_id": snapshot_id,
            "source_table": "PSCompPars",
            "source_file": source_file,
            "source_sha256": source_sha256,
            "source_row_number": source_row_number,
            "insolation_quality_status": insolation_status,
            "reported_parameter_count": present_parameter_count,
            "missing_parameter_labels": missing_parameter_labels,
        },
    }


def load_source_parameter_documents(
    definitions_path: Path,
    definitions_manifest_path: Path,
    *,
    snapshot_id: str,
    source_sha256: str,
    dataset_columns: Iterable[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load parameter documents extracted from frozen official NASA schema HTML.

    The JSONL is accepted only if its checksum and originating catalogue snapshot match
    the manifests. No manually authored parameter glossary is consulted.
    """
    if not definitions_path.is_file():
        raise FileNotFoundError(
            f"Source-derived parameter definitions not found: {definitions_path}. Run "
            "`python -m exotrace.vector.extract_parameter_definitions` first."
        )
    if not definitions_manifest_path.is_file():
        raise FileNotFoundError(
            f"Parameter-definition manifest not found: {definitions_manifest_path}. Run "
            "`python -m exotrace.vector.extract_parameter_definitions` first."
        )
    manifest_bytes = definitions_manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    content = definitions_path.read_bytes()
    actual_sha = sha256_bytes(content)
    if actual_sha != manifest.get("output_jsonl_sha256"):
        raise ValueError("Source parameter-definition JSONL checksum differs from its manifest.")
    if manifest.get("catalogue_snapshot_id") != snapshot_id:
        raise ValueError("Parameter definitions were extracted for a different catalogue snapshot.")
    if manifest.get("catalogue_source_sha256") != source_sha256:
        raise ValueError("Parameter definitions were extracted from a different catalogue source file.")
    if list(manifest.get("dataset_columns", [])) != list(dataset_columns):
        raise ValueError("Parameter-definition manifest dataset schema differs from the validated CSV.")
    if manifest.get("manual_glossary_used") is not False:
        raise ValueError("Parameter-definition manifest does not confirm source-derived extraction.")

    approved_hosts = {"exoplanetarchive.ipac.caltech.edu", "exoplanetarchive.nexsci.services"}
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(content.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            document = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid parameter document JSON on line {line_number}: {exc}") from exc
        doc_id = str(document.get("doc_id", ""))
        text = str(document.get("text", "")).strip()
        metadata = document.get("metadata") or {}
        if not doc_id or not text:
            raise ValueError(f"Parameter document on line {line_number} lacks ID or text.")
        if doc_id in seen_ids:
            raise ValueError(f"Duplicate parameter document ID: {doc_id}")
        seen_ids.add(doc_id)
        if document.get("doc_type") != "official_nasa_parameter_definition":
            raise ValueError(f"Unexpected parameter document type for {doc_id}.")
        parsed_url = urlparse(str(metadata.get("source_url", "")))
        if parsed_url.scheme != "https" or parsed_url.hostname not in approved_hosts:
            raise ValueError(f"Unapproved source URL on parameter document {doc_id}.")
        if metadata.get("source_raw_sha256") != manifest.get("source_raw_sha256"):
            raise ValueError(f"Source checksum mismatch in parameter document {doc_id}.")
        documents.append(document)
    if not documents:
        raise ValueError("Source-derived parameter-definition file contains no documents.")
    if not any((doc.get("metadata") or {}).get("parameter_field") == "pl_orbeccen" for doc in documents):
        raise ValueError("Parameter-definition corpus is missing the source-derived pl_orbeccen field.")
    return documents, manifest


def build_corpus_documents(
    dataframe: pd.DataFrame,
    reference_pages: Iterable[dict[str, Any]],
    *,
    snapshot_id: str,
    source_file: str,
    source_sha256: str,
    parameter_definition_documents: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build source chunks, NASA-extracted schema documents, and planet profiles."""
    documents: list[dict[str, Any]] = []

    for page in reference_pages:
        slug = str(page.get("slug") or "")
        page_title = REFERENCE_DISPLAY_TITLES.get(
            slug, str(page.get("title") or page.get("slug") or "NASA reference")
        )
        page_chunks = chunk_reference_text(str(page["text"]), page_title=page_title)
        for chunk_index, chunk in enumerate(page_chunks):
            doc_id = f"{page['doc_id']}:chunk:{chunk_index:04d}"
            section_heading = str(chunk["section_heading"])
            chunk_text = "\n\n".join(
                part for part in (page_title, f"Section: {section_heading}", chunk["body"])
                if part
            )
            documents.append(
                {
                    "doc_id": doc_id,
                    "doc_type": "official_nasa_reference_chunk",
                    "title": page_title,
                    "text": chunk_text,
                    "metadata": {
                        "source_doc_id": page["doc_id"],
                        "source_slug": slug,
                        "source_url": page["url"],
                        "publisher": page.get("publisher"),
                        "raw_file": page.get("raw_file"),
                        "raw_sha256": page.get("raw_sha256"),
                        "text_sha256": page.get("text_sha256"),
                        "chunk_index": chunk_index,
                        "section_heading": section_heading,
                        "word_count": chunk["word_count"],
                        "chunking_version": REFERENCE_CHUNKING_VERSION,
                        "source_type": "official_nasa_reference",
                    },
                }
            )

    documents.extend(parameter_definition_documents)

    for row_number, (_, row) in enumerate(dataframe.iterrows(), start=2):
        documents.append(
            _planet_profile(
                row,
                snapshot_id=snapshot_id,
                source_file=source_file,
                source_sha256=source_sha256,
                source_row_number=row_number,
            )
        )

    ids = [str(document["doc_id"]) for document in documents]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate document IDs encountered while assembling vector corpus.")
    if not documents or any(not str(doc.get("text", "")).strip() for doc in documents):
        raise ValueError("Vector corpus is empty or contains an empty text document.")
    return documents


def write_vector_corpus(*, force: bool = False) -> dict[str, Any]:
    """Create a fixed corpus from the verified planet snapshot and frozen reference pages."""
    corpus_path = PROJECT_ROOT / CORPUS_JSONL
    manifest_path = PROJECT_ROOT / CORPUS_MANIFEST
    if (corpus_path.exists() or manifest_path.exists()) and not force:
        raise FileExistsError(
            f"Vector corpus already exists ({corpus_path}). Use --force only when you "
            "intentionally "
            "want to replace the corpus and rebuild the vector index."
        )

    bundle = load_snapshot_bundle(PROJECT_ROOT)
    reference_pages_path = PROJECT_ROOT / REFERENCE_PAGES_JSONL
    reference_manifest_path = PROJECT_ROOT / REFERENCE_MANIFEST
    if not reference_manifest_path.is_file():
        raise FileNotFoundError(
            f"Reference-page manifest not found: {reference_manifest_path}. "
            "Run `python -m exotrace.vector.fetch_reference_docs` first."
        )
    reference_manifest = json.loads(reference_manifest_path.read_text(encoding="utf-8"))
    reference_pages_sha = sha256_bytes(reference_pages_path.read_bytes())
    if reference_manifest.get("reference_pages_jsonl_sha256") != reference_pages_sha:
        raise ValueError("Frozen reference-page text checksum differs from its manifest.")
    reference_pages = _load_reference_pages(reference_pages_path)
    if len(reference_pages) != int(reference_manifest.get("successful_page_count", -1)):
        raise ValueError("Reference-page count does not match the frozen manifest.")
    parameter_definitions, parameter_definition_manifest = load_source_parameter_documents(
        PROJECT_ROOT / PARAMETER_DEFINITIONS_JSONL,
        PROJECT_ROOT / PARAMETER_DEFINITIONS_MANIFEST,
        snapshot_id=bundle.snapshot_id,
        source_sha256=bundle.source_sha256,
        dataset_columns=bundle.dataframe.columns,
    )
    parameter_definitions_sha256 = sha256_bytes(
        (PROJECT_ROOT / PARAMETER_DEFINITIONS_JSONL).read_bytes()
    )
    parameter_definition_manifest_sha256 = sha256_bytes(
        (PROJECT_ROOT / PARAMETER_DEFINITIONS_MANIFEST).read_bytes()
    )
    docs = build_corpus_documents(
        bundle.dataframe,
        reference_pages,
        snapshot_id=bundle.snapshot_id,
        source_file=bundle.source_file,
        source_sha256=bundle.source_sha256,
        parameter_definition_documents=parameter_definitions,
    )

    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = "".join(_json_line(document) + "\n" for document in docs)
    temp_path = corpus_path.with_suffix(".jsonl.tmp")
    temp_path.write_text(serialized, encoding="utf-8")
    temp_path.replace(corpus_path)
    corpus_sha = sha256_bytes(corpus_path.read_bytes())
    doc_types = Counter(str(doc["doc_type"]) for doc in docs)
    manifest: dict[str, Any] = {
        "project": "ExoTrace",
        "built_at_utc": datetime.now(UTC).isoformat(),
        "corpus_file": CORPUS_JSONL.as_posix(),
        "corpus_sha256": corpus_sha,
        "document_count": len(docs),
        "document_counts_by_type": dict(sorted(doc_types.items())),
        "snapshot_id": bundle.snapshot_id,
        "catalogue_source_sha256": bundle.source_sha256,
        "reference_pages_file": REFERENCE_PAGES_JSONL.as_posix(),
        "reference_pages_sha256": reference_pages_sha,
        "reference_page_manifest_sha256": sha256_bytes(reference_manifest_path.read_bytes()),
        "parameter_definitions_file": PARAMETER_DEFINITIONS_JSONL.as_posix(),
        "parameter_definitions_sha256": parameter_definitions_sha256,
        "parameter_definition_manifest": PARAMETER_DEFINITIONS_MANIFEST.as_posix(),
        "parameter_definition_manifest_sha256": parameter_definition_manifest_sha256,
        "parameter_definition_document_count": len(parameter_definitions),
        "parameter_definition_source_sha256": parameter_definition_manifest.get("source_raw_sha256"),
        "parameter_definition_matched_column_coverage": parameter_definition_manifest.get("matched_column_coverage"),
        "profile_fields": [column for column, _, _ in PROFILE_FIELDS],
        "chunking_version": REFERENCE_CHUNKING_VERSION,
        "reference_target_words": REFERENCE_TARGET_WORDS,
        "reference_max_words": REFERENCE_MAX_WORDS,
        "notes": [
            "Planet profiles are generated search aids derived from the fixed catalogue snapshot.",
            "Numerical answers must be checked against source-linked CatalogueRecord properties.",
            "Missing values are described as unreported; no scientific values are imputed.",
            "Parameter-definition documents are extracted from the frozen official NASA schema HTML. No manually authored glossary is used.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Catalogue snapshot: {bundle.snapshot_id}")
    print(f"Reference pages: {len(reference_pages)}")
    print(f"Vector corpus documents: {len(docs):,}")
    for doc_type, count in sorted(doc_types.items()):
        print(f"  {doc_type}: {count:,}")
    print(f"Corpus SHA-256: {corpus_sha}")
    print(f"Corpus: {CORPUS_JSONL.as_posix()}")
    print(f"Manifest: {CORPUS_MANIFEST.as_posix()}")
    return manifest


def main() -> int:
    """CLI entry point for corpus assembly."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing corpus manifest and JSONL file; rebuild the index afterward.",
    )
    args = parser.parse_args()
    try:
        write_vector_corpus(force=args.force)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR building vector corpus: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
