"""Regression tests for Unicode output from the ExoTrace child CLI on Windows."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from exotrace.ui.service import _make_environment


def test_child_environment_forces_utf8_stdio_and_preserves_unicode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure Unicode report text can be printed even under a legacy Windows code page."""
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")

    environment = _make_environment(
        tmp_path,
        planner_output_tokens=5000,
        environment_overrides={"EXOTRACE_TEST_SETTING": "preserved"},
    )

    assert environment["PYTHONIOENCODING"].lower() == "utf-8"
    assert environment["EXOTRACE_TEST_SETTING"] == "preserved"

    completed = subprocess.run(
        [sys.executable, "-c", "print('\\ufb03')"],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=True,
    )

    assert completed.stdout == "\ufb03\n"
    assert completed.stderr == ""
