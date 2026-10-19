"""Validate a downloaded Exoplanet Archive snapshot and prepare a working CSV."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from exotrace.data.fetch_archive import COLUMNS, PROJECT_ROOT

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MANIFEST_DIR = PROJECT_ROOT / "data" / "manifests"
REQUIRED_KEYS = ("pl_name", "hostname")
NUMERIC_COLUMNS = (
    "sy_snum",
    "sy_pnum",
    "disc_year",
    "tran_flag",
    "rv_flag",
    "pl_orbper",
    "pl_orbpererr1",
    "pl_orbpererr2",
    "pl_orbperlim",
    "pl_orbsmax",
    "pl_orbsmaxerr1",
    "pl_orbsmaxerr2",
    "pl_orbsmaxlim",
    "pl_rade",
    "pl_radeerr1",
    "pl_radeerr2",
    "pl_radelim",
    "pl_bmasse",
    "pl_bmasseerr1",
    "pl_bmasseerr2",
    "pl_bmasselim",
    "pl_eqt",
    "pl_eqterr1",
    "pl_eqterr2",
    "pl_eqtlim",
    "pl_orbeccen",
    "pl_orbeccenerr1",
    "pl_orbeccenerr2",
    "pl_orbeccenlim",
    "pl_insol",
    "pl_insolerr1",
    "pl_insolerr2",
    "pl_insollim",
    "st_teff",
    "st_tefferr1",
    "st_tefferr2",
    "st_tefflim",
    "st_rad",
    "st_raderr1",
    "st_raderr2",
    "st_mass",
    "st_masserr1",
    "st_masserr2",
    "sy_dist",
    "sy_disterr1",
    "sy_disterr2",
)
POSITIVE_VALUE_COLUMNS = (
    "pl_orbper",
    "pl_orbsmax",
    "pl_rade",
    "pl_bmasse",
    "pl_eqt",
    "pl_insol",
    "st_teff",
    "st_rad",
    "st_mass",
    "sy_dist",
)


def find_latest_snapshot(raw_dir: Path = RAW_DIR) -> Path:
    """Return the most recently named CSV snapshot, or raise a helpful error."""
    candidates = sorted(raw_dir.glob("pscomppars_*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"No raw snapshot found in {raw_dir}. Run `python -m exotrace.data.fetch_archive` first."
        )
    return candidates[-1]


def normalize_text_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """Trim string cells and convert blank strings to missing values, without imputing."""
    normalized = frame.copy()
    for column in normalized.select_dtypes(include=["object", "string"]).columns:
        values = normalized[column].astype("string").str.strip()
        normalized[column] = values.mask(values.eq(""), pd.NA)
    return normalized


def validate_frame(frame: pd.DataFrame) -> dict[str, Any]:
    """Return data-quality diagnostics without silently dropping or repairing rows."""
    normalized = normalize_text_fields(frame)
    missing_columns = sorted(set(COLUMNS) - set(normalized.columns))

    missing_key_counts: dict[str, int] = {}
    for column in REQUIRED_KEYS:
        if column in normalized.columns:
            missing_key_counts[column] = int(
                normalized[column].isna().sum()
                + normalized[column].astype("string").str.strip().eq("").fillna(False).sum()
            )
        else:
            missing_key_counts[column] = int(len(normalized))

    duplicate_name_rows = 0
    duplicate_unique_names = 0
    if "pl_name" in normalized.columns:
        duplicate_mask = normalized["pl_name"].duplicated(keep=False) & normalized["pl_name"].notna()
        duplicate_name_rows = int(duplicate_mask.sum())
        duplicate_unique_names = int(normalized.loc[duplicate_mask, "pl_name"].nunique())

    missingness = {
        column: {
            "missing_count": int(normalized[column].isna().sum()),
            "missing_fraction": round(float(normalized[column].isna().mean()), 6),
        }
        for column in normalized.columns
    }

    numeric_checks: dict[str, dict[str, int]] = {}
    for column in NUMERIC_COLUMNS:
        if column not in normalized.columns:
            continue
        values = pd.to_numeric(normalized[column], errors="coerce")
        numeric_checks[column] = {
            "non_numeric_non_missing_count": int((normalized[column].notna() & values.isna()).sum()),
            "missing_after_numeric_parse_count": int(values.isna().sum()),
        }

    nonpositive_measurements: dict[str, int] = {}
    for column in POSITIVE_VALUE_COLUMNS:
        if column not in normalized.columns:
            continue
        values = pd.to_numeric(normalized[column], errors="coerce")
        nonpositive_measurements[column] = int((values.notna() & (values <= 0)).sum())

    errors: list[str] = []
    if missing_columns:
        errors.append("Missing expected columns: " + ", ".join(missing_columns))
    if any(missing_key_counts.values()):
        errors.append("One or more rows have missing required identifiers.")
    if duplicate_name_rows:
        errors.append(
            f"Found {duplicate_name_rows} rows across {duplicate_unique_names} duplicate planet names."
        )

    return {
        "validated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "row_count": int(len(normalized)),
        "column_count": int(len(normalized.columns)),
        "columns": list(normalized.columns),
        "missing_expected_columns": missing_columns,
        "required_key_missing_counts": missing_key_counts,
        "duplicate_planet_name_row_count": duplicate_name_rows,
        "duplicate_planet_name_unique_count": duplicate_unique_names,
        "missingness_by_column": missingness,
        "numeric_parse_checks": numeric_checks,
        "nonpositive_measurement_counts_review_required": nonpositive_measurements,
        "errors": errors,
        "passed": not errors,
        "notes": [
            "Missing scientific measurements are retained as missing; no values were imputed.",
            "Asymmetric uncertainty fields and limit flags are preserved unchanged.",
            "Nonpositive measurement counts are review flags, not automatic row deletions.",
            "The composite table may combine sources across parameters; inspect reference links.",
        ],
    }


def validate_latest_snapshot() -> tuple[Path, Path]:
    """Validate the latest snapshot, writing a processed CSV and a JSON report."""
    raw_path = find_latest_snapshot()
    frame = pd.read_csv(raw_path, low_memory=False)
    normalized = normalize_text_fields(frame)
    report = validate_frame(normalized)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = PROCESSED_DIR / "planets_validated.csv"
    report_path = MANIFEST_DIR / "validation_report.json"

    normalized.to_csv(processed_path, index=False)
    report["raw_file"] = str(raw_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    report["raw_sha256"] = _sha256_file(raw_path)
    report["processed_file"] = str(processed_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    report["processed_sha256"] = _sha256_file(processed_path)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Raw snapshot: {raw_path.relative_to(PROJECT_ROOT)}")
    print(f"Rows: {report['row_count']:,} | columns: {report['column_count']}")
    print(f"Validated CSV: {processed_path.relative_to(PROJECT_ROOT)}")
    print(f"Report: {report_path.relative_to(PROJECT_ROOT)}")
    print(f"Validation status: {'PASS' if report['passed'] else 'FAIL'}")
    if report["errors"]:
        for error in report["errors"]:
            print(f"  - {error}")
    return processed_path, report_path


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 digest of a file in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        _, report_path = validate_latest_snapshot()
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
