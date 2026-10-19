"""Tests for ExoTrace's data validation safeguards."""

from __future__ import annotations

import pandas as pd

from exotrace.data.fetch_archive import COLUMNS
from exotrace.data.validate_snapshot import normalize_text_fields, validate_frame


def _valid_frame() -> pd.DataFrame:
    """Build a complete-schema fixture with two simple planet records."""
    frame = pd.DataFrame({column: [pd.NA, pd.NA] for column in COLUMNS})
    frame["pl_name"] = ["Planet A", "Planet B"]
    frame["hostname"] = ["Star A", "Star B"]
    frame["pl_orbper"] = [1.5, 12.0]
    return frame


def test_validation_passes_for_unique_records_with_required_identifiers() -> None:
    """A valid table should pass identifier, schema, and duplicate checks."""
    report = validate_frame(_valid_frame())

    assert report["required_key_missing_counts"] == {"pl_name": 0, "hostname": 0}
    assert report["duplicate_planet_name_row_count"] == 0
    assert report["passed"] is True


def test_validation_detects_missing_identifiers_and_duplicate_names() -> None:
    """Missing keys and duplicate planet names must not be silently accepted."""
    frame = _valid_frame()
    frame.loc[1, "pl_name"] = "Planet A"
    frame.loc[1, "hostname"] = "Star A"
    frame.loc[0, "hostname"] = pd.NA

    report = validate_frame(frame)

    assert report["required_key_missing_counts"]["hostname"] == 1
    assert report["duplicate_planet_name_row_count"] == 2
    assert report["passed"] is False


def test_text_normalization_trims_blanks_without_filling_missing_values() -> None:
    """Text cleanup trims identifiers but never invents replacements for blanks."""
    frame = pd.DataFrame({"pl_name": [" Planet A ", "   ", None]})

    normalized = normalize_text_fields(frame)

    assert normalized.loc[0, "pl_name"] == "Planet A"
    assert pd.isna(normalized.loc[1, "pl_name"])
    assert pd.isna(normalized.loc[2, "pl_name"])
