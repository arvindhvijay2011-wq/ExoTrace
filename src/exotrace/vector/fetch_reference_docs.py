"""Download and freeze selected official NASA exoplanet reference pages.

This is an explicit ingestion step, not a live retrieval dependency. Once the source
pages have been captured, ExoTrace uses the local files until the user deliberately
runs this command with ``--refresh``.
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

import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIRECTORY = Path("data/raw/reference_pages")
PROCESSED_JSONL = Path("data/processed/reference_pages.jsonl")
MANIFEST_PATH = Path("data/manifests/reference_pages_manifest.json")
REQUEST_TIMEOUT_SECONDS = 25
MIN_SUCCESSFUL_PAGES = 3
USER_AGENT = "ExoTrace-portfolio-research/0.1 (NASA reference corpus; contact: local project)"

REFERENCE_PAGES: tuple[tuple[str, str, str], ...] = (
    (
        "exoplanet_overview",
        "NASA Exoplanets",
        "https://science.nasa.gov/exoplanets/",
    ),
    (
        "detection_methods",
        "How NASA Finds and Characterizes Exoplanets",
        "https://science.nasa.gov/exoplanets/how-we-find-and-characterize/",
    ),
    (
        "exoplanet_facts",
        "NASA Exoplanet Facts",
        "https://science.nasa.gov/exoplanets/facts/",
    ),
    (
        "habitable_zone",
        "The Habitable Zone",
        "https://science.nasa.gov/exoplanets/habitable-zone/",
    ),
    (
        "archive_parameter_columns",
        "NASA Exoplanet Archive PS Table Column Definitions",
        "https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html",
    ),
    (
        "composite_parameter_calculations",
        "NASA Exoplanet Archive Composite Parameter Calculations",
        "https://exoplanetarchive.ipac.caltech.edu/docs/pscp_calc.html",
    ),
    (
        "tap_query_documentation",
        "NASA Exoplanet Archive TAP Query Documentation",
        "https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html",
    ),
)


def sha256_bytes(content: bytes) -> str:
    """Return the lowercase SHA-256 digest for a byte string."""
    return hashlib.sha256(content).hexdigest()


def _slug_filename(slug: str) -> str:
    """Normalize a page slug to a conservative filename."""
    return re.sub(r"[^a-z0-9_-]+", "_", slug.casefold()).strip("_") + ".html"


def extract_page_text(html: str) -> tuple[str, str]:
    """Extract readable headings and prose while removing page chrome and scripts."""
    soup = BeautifulSoup(html, "html.parser")
    title = " ".join(soup.title.get_text(" ", strip=True).split()) if soup.title else ""

    for element in soup.select("script, style, noscript, svg, nav, footer, header, aside"):
        element.decompose()

    main = soup.find("main") or soup.find("article") or soup.find(id="content") or soup.body or soup
    pieces: list[str] = []
    for element in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "dt", "dd"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        if len(text) >= 25:
            pieces.append(text)

    if pieces:
        page_text = "\n\n".join(pieces)
    else:
        page_text = "\n".join(
            line.strip() for line in main.get_text("\n", strip=True).splitlines() if line.strip()
        )
    page_text = "\n".join(line.rstrip() for line in page_text.splitlines()).strip()
    return title, page_text


def _json_line(record: dict[str, Any]) -> str:
    """Serialize one UTF-8 JSONL record deterministically."""
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fetch_reference_pages(*, refresh: bool = False) -> dict[str, Any]:
    """Fetch official reference pages into a local, checksummed corpus snapshot."""
    manifest_path = PROJECT_ROOT / MANIFEST_PATH
    processed_path = PROJECT_ROOT / PROCESSED_JSONL
    if manifest_path.exists() and not refresh:
        raise FileExistsError(
            f"A frozen reference-page manifest already exists at {manifest_path}. "
            "To deliberately refresh sources, rerun with --refresh; otherwise keep the existing "
            "snapshot."
        )

    raw_dir = PROJECT_ROOT / RAW_DIRECTORY
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    )

    records: list[dict[str, Any]] = []
    page_status: list[dict[str, Any]] = []
    retrieved_at = datetime.now(UTC).isoformat()

    for slug, default_title, url in REFERENCE_PAGES:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "science.nasa.gov",
            "exoplanetarchive.ipac.caltech.edu",
        }:
            page_status.append({"slug": slug, "url": url, "status": "rejected_non_official_host"})
            continue

        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            raw_bytes = response.content
            html = response.text
            title, text = extract_page_text(html)
            if len(text) < 250:
                raise ValueError(f"Extracted text too short ({len(text)} characters).")

            raw_filename = _slug_filename(slug)
            raw_path = raw_dir / raw_filename
            raw_path.write_bytes(raw_bytes)
            raw_sha = sha256_bytes(raw_bytes)
            text_sha = sha256_bytes(text.encode("utf-8"))
            page_title = title or default_title
            record = {
                "doc_id": f"reference:{slug}",
                "doc_type": "official_nasa_reference",
                "slug": slug,
                "title": page_title,
                "url": url,
                "publisher": parsed.hostname,
                "text": text,
                "raw_file": RAW_DIRECTORY.as_posix() + "/" + raw_filename,
                "raw_sha256": raw_sha,
                "text_sha256": text_sha,
                "retrieved_at_utc": retrieved_at,
            }
            records.append(record)
            page_status.append(
                {
                    "slug": slug,
                    "title": page_title,
                    "url": url,
                    "status": "downloaded",
                    "raw_file": record["raw_file"],
                    "raw_sha256": raw_sha,
                    "text_sha256": text_sha,
                    "character_count": len(text),
                }
            )
            print(f"Downloaded: {slug} ({len(text):,} text characters)")
        except (requests.RequestException, ValueError) as exc:
            page_status.append({"slug": slug, "url": url, "status": "failed", "error": str(exc)})
            print(f"WARNING: Could not capture {url}: {exc}", file=sys.stderr)

    session.close()
    if len(records) < MIN_SUCCESSFUL_PAGES:
        raise RuntimeError(
            f"Only {len(records)} official pages were captured; at least {MIN_SUCCESSFUL_PAGES} "
            "are required. Check network access and retry with --refresh if a partial manifest "
            "exists."
        )

    temporary_path = processed_path.with_suffix(".jsonl.tmp")
    temporary_path.write_text(
        "".join(_json_line(record) + "\n" for record in records), encoding="utf-8"
    )
    temporary_path.replace(processed_path)

    manifest: dict[str, Any] = {
        "project": "ExoTrace",
        "source_policy": "Official NASA domains only; local frozen copy used after capture.",
        "retrieved_at_utc": retrieved_at,
        "minimum_successful_pages": MIN_SUCCESSFUL_PAGES,
        "successful_page_count": len(records),
        "requested_page_count": len(REFERENCE_PAGES),
        "reference_pages_jsonl": PROCESSED_JSONL.as_posix(),
        "reference_pages_jsonl_sha256": sha256_bytes(processed_path.read_bytes()),
        "pages": page_status,
        "refresh_required_to_replace_snapshot": True,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nCaptured {len(records)} of {len(REFERENCE_PAGES)} official NASA pages.")
    print(f"Frozen reference text: {PROCESSED_JSONL.as_posix()}")
    print(f"Manifest: {MANIFEST_PATH.as_posix()}")
    print(f"SHA-256: {manifest['reference_pages_jsonl_sha256']}")
    return manifest


def main() -> int:
    """Command-line entry point for freezing explanatory documents."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Explicitly replace the local reference-page snapshot with newly downloaded pages.",
    )
    args = parser.parse_args()
    try:
        fetch_reference_pages(refresh=args.refresh)
        return 0
    except (OSError, ValueError, RuntimeError, FileExistsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
