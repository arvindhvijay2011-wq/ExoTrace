"""Offline tests for evidence packing and citation-safe answer generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from exotrace.answering.grounded_answer import (
    AnswerGenerationError,
    OpenAIResponsesAnswerer,
    _load_local_settings,
    build_evidence_pack,
    render_markdown,
    validate_answer_payload,
)


def source_document(
    *,
    doc_id: str = "reference:archive_parameter_columns:chunk:field_pl_orbeccen",
    doc_type: str = "official_nasa_parameter_definition",
    title: str = "Eccentricity (pl_orbeccen)",
    text: str = (
        "Amount by which the orbit of the planet deviates "
        "from a perfect circle."
    ),
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a representative retrieved source document for testing."""
    return {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "title": title,
        "text": text,
        "metadata": {
            "source_url": (
                "https://exoplanetarchive.ipac.caltech.edu/"
                "docs/API_PS_columns.html"
            ),
            "parameter_field": "pl_orbeccen",
            **(dict(metadata) if metadata else {}),
        },
    }


def response_with_payload(generated: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal Responses API-style response for offline tests."""
    return {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(generated),
                    },
                ],
            }
        ]
    }


def test_build_evidence_pack_preserves_source_provenance() -> None:
    evidence = build_evidence_pack([source_document()])

    assert len(evidence) == 1
    assert evidence[0].evidence_id == "E1"
    assert evidence[0].source_url == (
        "https://exoplanetarchive.ipac.caltech.edu/"
        "docs/API_PS_columns.html"
    )
    assert evidence[0].metadata["parameter_field"] == "pl_orbeccen"


def test_build_evidence_pack_skips_documents_without_id_or_text() -> None:
    evidence = build_evidence_pack(
        [
            {"doc_id": "empty-text", "text": " "},
            {"text": "no id", "title": "invalid"},
            source_document(),
        ]
    )

    assert [item.doc_id for item in evidence] == [
        "reference:archive_parameter_columns:chunk:field_pl_orbeccen"
    ]
    assert evidence[0].evidence_id == "E1"


def test_build_evidence_pack_respects_per_document_character_limit() -> None:
    long_document = source_document(text="NASA source text. " * 100)

    evidence = build_evidence_pack(
        [long_document],
        max_document_chars=100,
    )

    assert len(evidence[0].text) <= 100
    assert evidence[0].truncated is True


def test_build_evidence_pack_rejects_invalid_character_budgets() -> None:
    with pytest.raises(ValueError, match="limits must be positive"):
        build_evidence_pack(
            [source_document()],
            max_document_chars=0,
        )


def test_validate_answer_payload_accepts_only_retrieved_citations() -> None:
    answerable, claims, reason = validate_answer_payload(
        {
            "answerable": True,
            "claims": [
                {
                    "text": (
                        "Eccentricity describes how much an orbit "
                        "departs from a circle."
                    ),
                    "evidence_ids": ["E1"],
                }
            ],
            "insufficient_reason": "",
        },
        valid_evidence_ids={"E1", "E2"},
    )

    assert answerable is True
    assert claims[0].evidence_ids == ("E1",)
    assert reason == ""


def test_validate_answer_payload_rejects_unknown_citation_id() -> None:
    with pytest.raises(AnswerGenerationError, match="not retrieved"):
        validate_answer_payload(
            {
                "answerable": True,
                "claims": [
                    {
                        "text": "Claim",
                        "evidence_ids": ["E99"],
                    }
                ],
                "insufficient_reason": "",
            },
            valid_evidence_ids={"E1"},
        )


def test_validate_answer_payload_requires_citation_per_claim() -> None:
    with pytest.raises(
        AnswerGenerationError,
        match="at least one evidence ID",
    ):
        validate_answer_payload(
            {
                "answerable": True,
                "claims": [
                    {
                        "text": "An uncited claim",
                        "evidence_ids": [],
                    }
                ],
                "insufficient_reason": "",
            },
            valid_evidence_ids={"E1"},
        )


def test_validate_answer_payload_requires_reason_for_abstention() -> None:
    with pytest.raises(AnswerGenerationError, match="explain why"):
        validate_answer_payload(
            {
                "answerable": False,
                "claims": [],
                "insufficient_reason": " ",
            },
            valid_evidence_ids={"E1"},
        )


def test_validate_answer_payload_rejects_claims_when_abstaining() -> None:
    with pytest.raises(
        AnswerGenerationError,
        match="must not include factual claims",
    ):
        validate_answer_payload(
            {
                "answerable": False,
                "claims": [
                    {
                        "text": "Claim",
                        "evidence_ids": ["E1"],
                    }
                ],
                "insufficient_reason": "Insufficient evidence.",
            },
            valid_evidence_ids={"E1"},
        )


def test_render_markdown_uses_validated_source_url() -> None:
    from exotrace.answering.grounded_answer import GroundedAnswer

    answerer = OpenAIResponsesAnswerer(
        api_key="test-key",
        model="test-model",
    )

    generated = {
        "answerable": True,
        "claims": [
            {
                "text": (
                    "Eccentricity describes departure "
                    "from a circular orbit."
                ),
                "evidence_ids": ["E1"],
            }
        ],
        "insufficient_reason": "",
    }

    evidence = build_evidence_pack([source_document()])

    answerable, claims, reason = validate_answer_payload(
        generated,
        valid_evidence_ids={
            item.evidence_id for item in evidence
        },
    )

    result = GroundedAnswer(
        query="Define eccentricity",
        answerable=answerable,
        claims=claims,
        insufficient_reason=reason,
        evidence=tuple(evidence),
        model=answerer.model,
        retrieval_strategy="dense",
        retrieval_scope="references",
        corpus_sha256="abc123",
        created_at_utc="2026-01-01T00:00:00+00:00",
    )

    markdown = render_markdown(result)

    assert "[E1]" in markdown
    assert (
        "https://exoplanetarchive.ipac.caltech.edu/"
        "docs/API_PS_columns.html"
    ) in markdown
    assert "Eccentricity describes departure" in markdown


def test_answerer_builds_structured_request_and_validates_citation() -> None:
    seen: dict[str, Any] = {}

    def fake_post_json(
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Capture the request and return a simulated API response."""
        seen.update(
            {
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )

        return response_with_payload(
            {
                "answerable": True,
                "claims": [
                    {
                        "text": (
                            "Eccentricity describes how much an orbit "
                            "deviates from a perfect circle."
                        ),
                        "evidence_ids": ["E1"],
                    }
                ],
                "insufficient_reason": "",
            }
        )

    answerer = OpenAIResponsesAnswerer(
        api_key="unit-test-secret",
        model="model-configured-in-test",
        post_json=fake_post_json,
    )

    result = answerer.answer(
        "What does eccentricity mean?",
        [source_document()],
        retrieval_strategy="dense",
        retrieval_scope="references",
        corpus_sha256="corpus-hash",
    )

    assert result.answerable is True
    assert result.claims[0].evidence_ids == ("E1",)
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["headers"]["Authorization"] == (
        "Bearer unit-test-secret"
    )
    assert seen["body"]["model"] == "model-configured-in-test"
    assert seen["body"]["text"]["format"]["type"] == "json_schema"
    assert (
        "Amount by which the orbit"
        in seen["body"]["input"][1]["content"][0]["text"]
    )


def test_answerer_rejects_fabricated_evidence_ids() -> None:
    def fake_post_json(
        _url: str,
        _headers: Mapping[str, str],
        _body: Mapping[str, Any],
        _timeout: float,
    ) -> dict[str, Any]:
        """Return a response with a citation that was not retrieved."""
        return response_with_payload(
            {
                "answerable": True,
                "claims": [
                    {
                        "text": "Unsupported",
                        "evidence_ids": ["E404"],
                    }
                ],
                "insufficient_reason": "",
            }
        )

    answerer = OpenAIResponsesAnswerer(
        api_key="test-key",
        model="test-model",
        post_json=fake_post_json,
    )

    with pytest.raises(AnswerGenerationError, match="not retrieved"):
        answerer.answer(
            "A question",
            [source_document()],
            retrieval_strategy="dense",
            retrieval_scope="references",
        )


def test_answerer_abstains_without_calling_model_when_no_documents_exist() -> None:
    def fail_if_called(
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Fail if answer generation is attempted without evidence."""
        raise AssertionError(
            "The model should not be called with no evidence."
        )

    answerer = OpenAIResponsesAnswerer(
        api_key="test-key",
        model="test-model",
        post_json=fail_if_called,
    )

    result = answerer.answer(
        "A question",
        [],
        retrieval_strategy="dense",
        retrieval_scope="references",
    )

    assert result.answerable is False
    assert result.claims == ()
    assert "no usable evidence" in result.insufficient_reason


def test_load_local_settings_does_not_override_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify .env fallback and process-environment precedence."""
    (tmp_path / ".env").write_text(
        'OPENAI_API_KEY="local-key"\nEXOTRACE_LLM_MODEL=local-model\n',
        encoding="utf-8",
    )

    # Isolate this test from an API key inherited from the host process.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # The process environment must override this value from .env.
    monkeypatch.setenv("EXOTRACE_LLM_MODEL", "process-model")

    settings = _load_local_settings(tmp_path)

    assert settings["OPENAI_API_KEY"] == "local-key"
    assert settings["EXOTRACE_LLM_MODEL"] == "process-model"