"""Regression tests for answer grouping and local-only Neo4j credentials."""

from pathlib import Path
from typing import Any

from exotrace.ui.presentation import group_answer_claims


def test_claims_sharing_a_catalogue_record_are_grouped_under_one_source() -> None:
    payload: dict[str, Any] = {
        "answerable": True,
        "claims": [
            {"text": "Kepler-10 b was discovered using the transit method in 2011.", "evidence_ids": ["E1"]},
            {"text": "Kepler-10 b has a radius of 1.47 Earth radii.", "evidence_ids": ["E1"]},
            {"text": "Kepler-10 b has a mass of 3.24 Earth masses.", "evidence_ids": ["E1"]},
            {"text": "Kepler-10 c has a radius of 2.355 Earth radii.", "evidence_ids": ["E2"]},
        ],
        "evidence": [
            {"evidence_id": "E1", "title": "Kepler-10 b catalogue record"},
            {"evidence_id": "E2", "title": "Kepler-10 c catalogue record"},
        ],
    }

    groups = group_answer_claims(payload)

    assert len(groups) == 2
    assert groups[0]["title"] == "Kepler-10 b catalogue record"
    assert groups[0]["evidence_ids"] == ["E1"]
    assert len(groups[0]["claims"]) == 3
    assert groups[1]["title"] == "Kepler-10 c catalogue record"
    assert groups[1]["claims"] == ["Kepler-10 c has a radius of 2.355 Earth radii."]


def test_claims_without_citations_are_grouped_without_fabricating_sources() -> None:
    groups = group_answer_claims({
        "claims": [
            {"text": "A cautious unsourced note.", "evidence_ids": []},
            {"text": "Another note.", "evidence_ids": None},
        ],
        "evidence": [],
    })

    assert len(groups) == 1
    assert groups[0]["title"] == "Finding"
    assert groups[0]["evidence_ids"] == []
    assert len(groups[0]["claims"]) == 2


def test_frontend_never_collects_neo4j_password_from_user() -> None:
    app_path = Path(__file__).parents[1] / "src" / "exotrace" / "ui" / "app.py"
    source = app_path.read_text(encoding="utf-8")

    assert 'st.text_input(\n                "Neo4j password' not in source
    assert 'controls.get("neo4j_password")' not in source
    assert "NEO4J_PASSWORD is not configured" in source
    assert ".env file" in source
