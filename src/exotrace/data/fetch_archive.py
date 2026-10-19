"""Download a reproducible snapshot from the NASA Exoplanet Archive TAP service."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from io import BytesIO
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

import pandas as pd
import requests

TAP_SYNC_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
SCHEMA_DOC_URL = "https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html"
TAP_DOC_URL = "https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html"
DATA_DOI = "10.26133/NEA2"

# Keep only fields that are useful for graph relationships, scientific comparisons,
# uncertainty-aware reporting, and source traceability. Their definitions are documented
# by the archive. Reference links and limit/error columns are intentionally retained.
COLUMNS: tuple[str, ...] = (
    "pl_name",
    "hostname",
    "sy_snum",
    "sy_pnum",
    "cb_flag",
    "pl_controv_flag",
    "discoverymethod",
    "disc_year",
    "disc_locale",
    "disc_refname",
    "disc_pubdate",
    "disc_facility",
    "disc_telescope",
    "disc_instrument",
    "tran_flag",
    "rv_flag",
    "pl_orbper",
    "pl_orbpererr1",
    "pl_orbpererr2",
    "pl_orbperlim",
    "pl_orbper_reflink",
    "pl_orbsmax",
    "pl_orbsmaxerr1",
    "pl_orbsmaxerr2",
    "pl_orbsmaxlim",
    "pl_orbsmax_reflink",
    "pl_rade",
    "pl_radeerr1",
    "pl_radeerr2",
    "pl_radelim",
    "pl_rade_reflink",
    "pl_bmasse",
    "pl_bmasseerr1",
    "pl_bmasseerr2",
    "pl_bmasselim",
    "pl_bmasse_reflink",
    "pl_bmassprov",
    "pl_eqt",
    "pl_eqterr1",
    "pl_eqterr2",
    "pl_eqtlim",
    "pl_eqt_reflink",
    "pl_orbeccen",
    "pl_orbeccenerr1",
    "pl_orbeccenerr2",
    "pl_orbeccenlim",
    "pl_orbeccen_reflink",
    "pl_insol",
    "pl_insolerr1",
    "pl_insolerr2",
    "pl_insollim",
    "pl_insol_reflink",
    "st_teff",
    "st_tefferr1",
    "st_tefferr2",
    "st_tefflim",
    "st_teff_reflink",
    "st_rad",
    "st_raderr1",
    "st_raderr2",
    "st_rad_reflink",
    "st_mass",
    "st_masserr1",
    "st_masserr2",
    "st_mass_reflink",
    "st_spectype",
    "sy_dist",
    "sy_disterr1",
    "sy_disterr2",
    "sy_dist_reflink",
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"


def build_query(columns: Sequence[str] = COLUMNS) -> str:
    """Build a stable, explicit query instead of downloading an opaque `SELECT *`."""
    return f"select {', '.join(columns)} from pscomppars order by pl_name"


def sha256_bytes(content: bytes) -> str:
    """Return the lowercase SHA-256 digest for a byte sequence."""
    return hashlib.sha256(content).hexdigest()


def fetch_snapshot(*, timeout_seconds: int = 180) -> Path:
    """Download CSV data and write an adjacent provenance manifest.

    The raw CSV is saved byte-for-byte as returned by the TAP service. It is never
    overwritten silently: use a timestamped filename so snapshots remain auditable.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    query = build_query()
    response = requests.get(
        TAP_SYNC_URL,
        params={"query": query, "format": "csv"},
        headers={"User-Agent": "ExoTrace/0.1.0 (reproducible research prototype)"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()

    content = response.content
    try:
        frame = pd.read_csv(BytesIO(content))
    except Exception as exc:  # pandas provides useful parse errors for HTML/API error pages too.
        raise RuntimeError(
            "The NASA TAP response was not parseable as CSV. Check the service response "
            "and the requested column names before retrying."
        ) from exc

    expected_columns = set(COLUMNS)
    returned_columns = set(frame.columns)
    missing_columns = sorted(expected_columns - returned_columns)
    if missing_columns:
        raise RuntimeError(
            "The TAP response is missing requested columns: " + ", ".join(missing_columns)
        )
    if frame.empty:
        raise RuntimeError("NASA TAP returned zero data rows; no snapshot was written.")

    retrieved_at = datetime.now(UTC).replace(microsecond=0)
    timestamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    raw_path = RAW_DIR / f"pscomppars_{timestamp}.csv"
    raw_path.write_bytes(content)

    manifest = {
        "project": "ExoTrace",
        "source": "NASA Exoplanet Archive",
        "source_table": "pscomppars",
        "tap_sync_url": TAP_SYNC_URL,
        "query": query,
        "request_parameters": {"format": "csv"},
        "retrieved_at_utc": retrieved_at.isoformat(),
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": list(frame.columns),
        "sha256": sha256_bytes(content),
        "raw_file": str(raw_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "schema_documentation_url": SCHEMA_DOC_URL,
        "tap_documentation_url": TAP_DOC_URL,
        "archive_doi": DATA_DOI,
        "caveat": (
            "PSCompPars is designed for population-level analysis. Different parameters "
            "may have different sources or may be calculated; preserve parameter-level "
            "references, uncertainty fields, and limit flags."
        ),
    }
    manifest_path = MANIFEST_DIR / f"pscomppars_{timestamp}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Downloaded {len(frame):,} rows and {len(frame.columns)} columns.")
    print(f"Raw snapshot: {raw_path.relative_to(PROJECT_ROOT)}")
    print(f"Manifest:     {manifest_path.relative_to(PROJECT_ROOT)}")
    print(f"SHA-256:      {manifest['sha256']}")
    return raw_path


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the download step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="HTTP timeout in seconds (default: 180).",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    try:
        fetch_snapshot(timeout_seconds=args.timeout)
    except (requests.RequestException, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
