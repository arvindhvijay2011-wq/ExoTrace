"""Regression tests for coherent synthesis over catalogue, graph, and vector evidence."""

from __future__ import annotations

import json
from typing import Any, Mapping

from exotrace.agents.synthesis import AnswerSynthesisAgent
from exotrace.answering.grounded_answer import (
    GroundedAnswer,
    OpenAIResponsesAnswerer,
    SYSTEM_PROMPT,
)
from exotrace.contracts import EvidenceReference
from exotrace.ui.presentation import render_cited_claims_paragraph

PLANET_NAME = "2MASS J03590986+2009361 b"


def evidence(
    evidence_id: str,
    *,
    source_kind: str,
    title: str,
    excerpt: str,
    source_id: str,
    source_uri: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceReference:
    """Build typed evidence from one of ExoTrace's distinct source surfaces."""
    return EvidenceReference(
        evidence_id=evidence_id,
        source_id=source_id,
        title=title,
        excerpt=excerpt,
        source_uri=source_uri,
        source_kind=source_kind,
        snapshot_id="snapshot:multisource-test",
        record_id=source_id,
        metadata=dict(metadata or {}),
    )


def multi_source_report() -> dict[str, Any]:
    """Return one report with catalogue, graph, and frozen-reference evidence."""
    items = (
        (
            "catalogue_data",
            evidence(
                "catalogue:planet-profile",
                source_kind="NASA Exoplanet Archive PSCompPars catalogue record",
                title=f"{PLANET_NAME} catalogue record",
                excerpt=json.dumps(
                    {
                        "pl_name": PLANET_NAME,
                        "pl_rade": "12.2",
                        "pl_bmasse": "5720.911326",
                        "disc_year": "2024",
                    }
                ),
                source_id=f"record:{PLANET_NAME}",
            ),
        ),
        (
            "graph_investigation",
            evidence(
                "graph:host-relationship",
                source_kind="neo4j_graph_relationship",
                title=f"Graph relationship: host star HOSTS {PLANET_NAME}",
                excerpt=(
                    "The graph records a HOSTS relationship from host star "
                    "'2MASS J03590986+2009361' to planet '2MASS J03590986+2009361 b'."
                ),
                source_id="neo4j:HOSTS:planet-record",
                metadata={"relationship_type": "HOSTS"},
            ),
        ),
        (
            "literature_definition",
            evidence(
                "reference:disc-year-definition",
                source_kind="official_nasa_parameter_definition",
                title="Discovery Year (disc_year)",
                excerpt="The year the planet was discovered.",
                source_id="reference:disc-year-definition",
                source_uri="https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html",
                metadata={
                    "document_metadata": {
                        "parameter_field": "disc_year",
                        "table_label": "Discovery Year",
                        "source_type": "official_nasa_parameter_definition",
                    }
                },
            ),
        ),
    )
    return {
        "question": f"Tell me something about this planet {PLANET_NAME}.",
        "status": "completed",
        "results": [
            {
                "task_id": f"task-{index}",
                "agent_id": agent_id,
                "status": "succeeded",
                "summary": "Retrieved source-backed evidence.",
                "findings": [],
                "evidence": [item.to_dict()],
                "gaps": [],
                "tool_ids_used": [],
                "metadata": {},
            }
            for index, (agent_id, item) in enumerate(items, start=1)
        ],
    }


def test_synthesis_receives_complementary_evidence_from_all_three_source_types() -> None:
    captured: dict[str, Any] = {}
    generated = {
        "answerable": True,
        "claims": [
            {"text": "The catalogue records a radius of 12.2 Earth radii.", "evidence_ids": ["E1"]},
            {"text": "The graph links it to its host star.", "evidence_ids": ["E2"]},
            {
                "text": "The reference passage defines the discovery-year field.",
                "evidence_ids": ["E3"],
            },
        ],
        "insufficient_reason": "",
    }

    def fake_post_json(
        _url: str,
        _headers: Mapping[str, str],
        body: Mapping[str, Any],
        _timeout: float,
    ) -> dict[str, Any]:
        captured["body"] = dict(body)
        return {"output_text": json.dumps(generated)}

    answerer = OpenAIResponsesAnswerer(
        api_key="offline-test-key",
        model="offline-test-model",
        post_json=fake_post_json,
    )
    result = AnswerSynthesisAgent(answerer=answerer).synthesize(multi_source_report())
    request = captured["body"]
    user_payload = json.loads(request["input"][1]["content"][0]["text"])
    evidence_types = {item["doc_type"] for item in user_payload["evidence"]}

    assert len(user_payload["evidence"]) == 3
    assert any("catalogue record" in value.casefold() for value in evidence_types)
    assert "neo4j_graph_relationship" in evidence_types
    assert "official_nasa_parameter_definition" in evidence_types
    assert result.answer.answerable is True
    assert tuple(claim.evidence_ids for claim in result.answer.claims) == (
        ("E1",),
        ("E2",),
        ("E3",),
    )
    system_prompt = request["input"][0]["content"][0]["text"]
    assert "one coherent, natural explanation" in system_prompt
    assert "graph evidence supports the relationships explicitly represented" in system_prompt
    assert "general documentation as research about the specific object" in system_prompt


def test_rendered_claims_form_one_narrative_paragraph_without_losing_citations() -> None:
    captured: dict[str, Any] = {}
    generated = {
        "answerable": True,
        "claims": [
            {"text": "The catalogue records the planet's radius.", "evidence_ids": ["E1"]},
            {"text": "The graph identifies its host star.", "evidence_ids": ["E2"]},
            {"text": "A reference passage explains the field definition.", "evidence_ids": ["E3"]},
        ],
        "insufficient_reason": "",
    }

    def fake_post_json(
        _url: str,
        _headers: Mapping[str, str],
        body: Mapping[str, Any],
        _timeout: float,
    ) -> dict[str, Any]:
        captured["body"] = dict(body)
        return {"output_text": json.dumps(generated)}

    # Use the public source-backed report interface exercised by the prior test; the input list
    # above documents that rendering is not permitted to invent or consolidate evidence IDs.
    report = multi_source_report()
    answerer = OpenAIResponsesAnswerer(
        api_key="offline-test-key",
        model="offline-test-model",
        post_json=fake_post_json,
    )
    result = AnswerSynthesisAgent(answerer=answerer).synthesize(report)
    markdown = result.to_dict()["markdown"]
    answer_paragraph = markdown.split("### Sources", maxsplit=1)[0]

    assert (
        "The catalogue records the planet's radius. [E1] "
        "The graph identifies its host star. [E2]" in answer_paragraph
    )
    assert "A reference passage explains the field definition. [E3]" in answer_paragraph
    assert "\n\nThe graph identifies its host star" not in answer_paragraph


def test_ui_narrative_keeps_claim_level_citation_ids_inline() -> None:
    """The UI presents all source-backed claims as one paragraph without dropping citations."""
    paragraph = render_cited_claims_paragraph(
        {
            "answerable": True,
            "claims": [
                {"text": "The catalogue records the radius.", "evidence_ids": ["E1"]},
                {"text": "The graph identifies its host.", "evidence_ids": ["E2"]},
                {"text": "The reference defines the parameter.", "evidence_ids": ["E3"]},
            ],
        }
    )

    assert paragraph == (
        "The catalogue records the radius. [E1] The graph identifies its host. [E2] "
        "The reference defines the parameter. [E3]"
    )
