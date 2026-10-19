"""Tests for the standalone Answer Synthesis Agent."""

from __future__ import annotations

import json
from typing import Any, Mapping

import pytest

from exotrace.agents.synthesis import AnswerSynthesisAgent, AnswerSynthesisError
from exotrace.answering.grounded_answer import (
    AnswerGenerationError,
    OpenAIResponsesAnswerer,
)
from exotrace.contracts import EvidenceReference


def evidence(
    evidence_id: str = "literature:reference:field_pl_orbeccen",
    *,
    source_id: str = "reference:field_pl_orbeccen",
    title: str = "Eccentricity (pl_orbeccen)",
    excerpt: str = "Amount by which the orbit of the planet deviates from a perfect circle.",
    source_uri: str = "https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html",
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceReference:
    """Build a realistic source reference for an investigation report."""
    return EvidenceReference(
        evidence_id=evidence_id,
        source_id=source_id,
        title=title,
        excerpt=excerpt,
        source_uri=source_uri,
        source_kind="official_nasa_parameter_definition",
        snapshot_id="PSCompPars::test-snapshot",
        record_id=source_id,
        metadata=dict(metadata or {}),
    )


def report_payload(*items: EvidenceReference, status: str = "completed") -> dict[str, Any]:
    """Build the same serialized report shape produced by the investigation CLI."""
    return {
        "question": "What does planetary orbital eccentricity describe?",
        "status": status,
        "results": [
            {
                "task_id": "task-1",
                "agent_id": "literature_definition",
                "status": "succeeded",
                "summary": f"Retrieved {len(items)} reference passage(s).",
                "findings": [],
                "evidence": [item.to_dict() for item in items],
                "gaps": [],
                "tool_ids_used": ["literature.search"],
                "metadata": {},
            }
        ],
    }


def make_agent(
    generated: Mapping[str, Any],
    captured: dict[str, Any] | None = None,
) -> AnswerSynthesisAgent:
    """Create the real grounded answerer with a fake, schema-compatible API response."""
    def fake_post_json(
        _url: str,
        _headers: Mapping[str, str],
        body: Mapping[str, Any],
        _timeout: float,
    ) -> dict[str, Any]:
        if captured is not None:
            captured["body"] = dict(body)
        return {"output_text": json.dumps(dict(generated))}

    answerer = OpenAIResponsesAnswerer(
        api_key="unit-test-key",
        model="configured-test-model",
        post_json=fake_post_json,
    )
    return AnswerSynthesisAgent(answerer=answerer)


def test_synthesis_generates_cited_answer_and_preserves_source_provenance() -> None:
    captured: dict[str, Any] = {}
    source = evidence()
    agent = make_agent(
        {
            "answerable": True,
            "claims": [
                {
                    "text": "Eccentricity describes departure from a circular orbit.",
                    "evidence_ids": ["E1"],
                }
            ],
            "insufficient_reason": "",
        },
        captured,
    )

    result = agent.synthesize(report_payload(source))
    serialized = result.to_dict()

    assert result.answer.answerable is True
    assert result.answer.claims[0].evidence_ids == ("E1",)
    assert result.answer.evidence[0].doc_id == source.evidence_id
    assert result.answer.evidence[0].source_url == source.source_uri
    assert serialized["input_evidence_ids"] == [source.evidence_id]
    assert serialized["synthesis_agent"]["agent_id"] == "answer_synthesis"
    assert "[E1]" in serialized["markdown"]


def test_synthesis_passes_all_source_evidence_and_lets_model_select_relevant_sources() -> None:
    captured: dict[str, Any] = {}
    relevant = evidence()
    unrelated = evidence(
        "literature:reference:angular_separation",
        source_id="reference:angular_separation",
        title="Angular Separation",
        excerpt="The angular projected separation is calculated from semi-major axis and distance.",
        source_uri="https://exoplanetarchive.ipac.caltech.edu/docs/pscp_calc.html",
    )
    agent = make_agent(
        {
            "answerable": True,
            "claims": [
                {
                    "text": "Eccentricity describes departure from a circular orbit.",
                    "evidence_ids": ["E1"],
                }
            ],
            "insufficient_reason": "",
        },
        captured,
    )

    result = agent.synthesize(report_payload(relevant, unrelated))
    user_payload = json.loads(captured["body"]["input"][1]["content"][0]["text"])

    assert len(user_payload["evidence"]) == 2
    assert result.answer.claims[0].evidence_ids == ("E1",)
    assert result.answer.evidence[0].doc_id == relevant.evidence_id
    assert all(item.doc_id != unrelated.evidence_id for item in result.answer.evidence[:1])


def test_synthesis_deduplicates_identical_evidence_ids() -> None:
    source = evidence()
    captured: dict[str, Any] = {}
    agent = make_agent(
        {
            "answerable": True,
            "claims": [{"text": "A supported claim.", "evidence_ids": ["E1"]}],
            "insufficient_reason": "",
        },
        captured,
    )

    result = agent.synthesize(report_payload(source, source))
    user_payload = json.loads(captured["body"]["input"][1]["content"][0]["text"])

    assert len(result.input_evidence_ids) == 1
    assert len(user_payload["evidence"]) == 1


def test_synthesis_rejects_conflicting_content_for_same_evidence_id() -> None:
    original = evidence()
    conflicting = evidence(excerpt="Different text attached to the same evidence ID.")
    agent = make_agent(
        {
            "answerable": True,
            "claims": [{"text": "A claim.", "evidence_ids": ["E1"]}],
            "insufficient_reason": "",
        }
    )

    with pytest.raises(AnswerSynthesisError, match="conflicting source content"):
        agent.synthesize(report_payload(original, conflicting))


def test_plan_only_report_is_rejected_before_answerer_is_called() -> None:
    class NeverCalledAnswerer:
        model = "configured-test-model"

        def answer(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("Answerer must not run for a plan-only report.")

    agent = AnswerSynthesisAgent(answerer=NeverCalledAnswerer())
    with pytest.raises(AnswerSynthesisError, match="Execute the plan first"):
        agent.synthesize(report_payload(evidence(), status="planned"))


def test_no_usable_evidence_abstains_without_calling_the_api() -> None:
    def fail_if_called(
        _url: str,
        _headers: Mapping[str, str],
        _body: Mapping[str, Any],
        _timeout: float,
    ) -> dict[str, Any]:
        raise AssertionError("Empty evidence must not trigger an API request.")

    answerer = OpenAIResponsesAnswerer(
        api_key="unit-test-key",
        model="configured-test-model",
        post_json=fail_if_called,
    )
    agent = AnswerSynthesisAgent(answerer=answerer)
    result = agent.synthesize(report_payload())

    assert result.answer.answerable is False
    assert result.answer.claims == ()
    assert "no usable evidence" in result.answer.insufficient_reason.lower()


def test_unknown_citation_from_model_is_rejected() -> None:
    agent = make_agent(
        {
            "answerable": True,
            "claims": [{"text": "Unsupported citation.", "evidence_ids": ["E99"]}],
            "insufficient_reason": "",
        }
    )

    with pytest.raises(AnswerSynthesisError, match="not retrieved"):
        agent.synthesize(report_payload(evidence()))


def test_malformed_report_and_bad_evidence_are_rejected() -> None:
    agent = make_agent(
        {
            "answerable": False,
            "claims": [],
            "insufficient_reason": "Insufficient evidence.",
        }
    )

    with pytest.raises(AnswerSynthesisError, match="no usable question"):
        agent.synthesize({"status": "completed", "results": []})
    with pytest.raises(AnswerSynthesisError, match="(?i)evidence item"):
        agent.synthesize(
            {
                "question": "Question?",
                "status": "completed",
                "results": [{"evidence": [{"evidence_id": "missing-fields"}]}],
            }
        )


def test_answer_generation_errors_are_reported_as_synthesis_errors() -> None:
    class FailingAnswerer:
        model = "configured-test-model"

        def answer(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AnswerGenerationError("simulated API failure")

    agent = AnswerSynthesisAgent(answerer=FailingAnswerer())
    with pytest.raises(AnswerSynthesisError, match="simulated API failure"):
        agent.synthesize(report_payload(evidence()))

def test_synthesis_filters_derived_association_for_general_definition_question() -> None:
    captured: dict[str, Any] = {}
    primary = evidence(
        "literature:reference:field_pl_orbeccen",
        source_id="reference:field_pl_orbeccen",
        title="Eccentricity (pl_orbeccen)",
        excerpt="Amount by which the orbit of the planet deviates from a perfect circle.",
        metadata={
            "document_metadata": {
                "parameter_field": "pl_orbeccen",
                "table_label": "Eccentricity",
            }
        },
    )
    derived_limit = evidence(
        "literature:reference:field_pl_orbeccenlim",
        source_id="reference:field_pl_orbeccenlim",
        title="Eccentricity limit column (pl_orbeccenlim)",
        excerpt=(
            "This is the limit-column association for Eccentricity (pl_orbeccen). "
            "The parent definition describes departure from a perfect circle."
        ),
        metadata={
            "document_metadata": {
                "definition_extraction": "derived_from_official_limit_column_association",
                "parameter_field": "pl_orbeccenlim",
                "related_parameter_field": "pl_orbeccen",
            }
        },
    )
    agent = make_agent(
        {
            "answerable": True,
            "claims": [
                {
                    "text": "Eccentricity describes how much an orbit deviates from a perfect circle.",
                    "evidence_ids": ["E1"],
                }
            ],
            "insufficient_reason": "",
        },
        captured,
    )

    result = agent.synthesize(report_payload(primary, derived_limit))
    user_payload = json.loads(captured["body"]["input"][1]["content"][0]["text"])

    assert [item["title"] for item in user_payload["evidence"]] == [
        "Eccentricity (pl_orbeccen)"
    ]
    assert result.input_evidence_ids == (primary.evidence_id,)
    assert all(item.doc_id != derived_limit.evidence_id for item in result.answer.evidence)


def test_synthesis_retains_derived_association_when_user_asks_about_it() -> None:
    captured: dict[str, Any] = {}
    primary = evidence(
        "literature:reference:field_pl_orbeccen",
        source_id="reference:field_pl_orbeccen",
        title="Eccentricity (pl_orbeccen)",
        excerpt="Amount by which the orbit of the planet deviates from a perfect circle.",
        metadata={
            "document_metadata": {
                "parameter_field": "pl_orbeccen",
                "table_label": "Eccentricity",
            }
        },
    )
    derived_limit = evidence(
        "literature:reference:field_pl_orbeccenlim",
        source_id="reference:field_pl_orbeccenlim",
        title="Eccentricity limit column (pl_orbeccenlim)",
        excerpt="The NASA table associates pl_orbeccenlim with the eccentricity parameter.",
        metadata={
            "document_metadata": {
                "definition_extraction": "derived_from_official_limit_column_association",
                "parameter_field": "pl_orbeccenlim",
                "related_parameter_field": "pl_orbeccen",
            }
        },
    )
    agent = make_agent(
        {
            "answerable": True,
            "claims": [
                {
                    "text": "pl_orbeccenlim is the associated limit column for eccentricity.",
                    "evidence_ids": ["E2"],
                }
            ],
            "insufficient_reason": "",
        },
        captured,
    )

    result = agent.synthesize(
        {
            **report_payload(primary, derived_limit),
            "question": "What does the pl_orbeccenlim field represent?",
        }
    )
    user_payload = json.loads(captured["body"]["input"][1]["content"][0]["text"])

    assert [item["title"] for item in user_payload["evidence"]] == [
        "Eccentricity (pl_orbeccen)",
        "Eccentricity limit column (pl_orbeccenlim)",
    ]
    assert derived_limit.evidence_id in result.input_evidence_ids


def test_grounded_answer_prompt_discourages_adjacent_facts_and_repetition() -> None:
    from exotrace.answering.grounded_answer import SYSTEM_PROMPT

    assert "Do not introduce adjacent facts merely because they appear" in SYSTEM_PROMPT
    assert "Do not restate the same meaning in multiple paraphrases" in SYSTEM_PROMPT
