"""Synthesize a final, citation-grounded answer from a completed investigation report.

The synthesis agent has no retrieval or database tools. It receives only provenance-bearing
source evidence collected by the specialist layer and delegates one structured generation
call to ExoTrace's existing grounded-answer component. Citation IDs are validated against the
current synthesis evidence pack; this is a structural safeguard, not proof of semantic entailment.

Run this module with ``python -m exotrace.agents.synthesis --help`` to synthesize a saved
investigation JSON report without modifying the existing investigation CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from exotrace.agents.orchestrator import InvestigationStatus
from exotrace.answering.evidence_selection import select_answer_evidence
from exotrace.answering.grounded_answer import (
    AnswerGenerationError,
    GroundedAnswer,
    OpenAIResponsesAnswerer,
    render_markdown,
)
from exotrace.contracts import EvidenceReference
from exotrace.vector.build_index import PROJECT_ROOT


class Answerer(Protocol):
    """Minimal interface required from the existing grounded-answer component."""

    model: str

    def answer(
        self,
        query: str,
        documents: Sequence[Mapping[str, Any]],
        *,
        retrieval_strategy: str,
        retrieval_scope: str,
        corpus_sha256: str | None = None,
    ) -> GroundedAnswer:
        """Generate a grounded answer from source documents."""
        ...


class AnswerSynthesisError(RuntimeError):
    """Raised when a report cannot be safely converted into a synthesis input."""


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """A synthesized answer with input-evidence identity and investigation provenance."""

    investigation_status: str
    input_evidence_ids: tuple[str, ...]
    answer: GroundedAnswer

    def to_dict(self) -> dict[str, Any]:
        """Serialize the answer, source traceability, and rendered response."""
        payload = self.answer.to_dict()
        payload["investigation_status"] = self.investigation_status
        payload["input_evidence_ids"] = list(self.input_evidence_ids)
        payload["synthesis_agent"] = {
            "agent_id": "answer_synthesis",
            "name": "Answer Synthesis Agent",
            "responsibility": (
                "Synthesize a focused response from specialist evidence without retrieving "
                "new evidence or executing tools."
            ),
        }
        payload["markdown"] = render_markdown(self.answer)
        return payload


class AnswerSynthesisAgent:
    """Turn structured specialist evidence into a concise answer with claim-level citations.

    This agent's sole job is answer synthesis. It has no tool executor, does not select
    specialists, does not retrieve more documents, does not calculate measurements, and does
    not perform a mandatory second verification-model call. It delegates exactly one answer
    generation request when usable evidence exists. If there is no evidence, the grounded
    answerer returns an abstention without calling the model.
    """

    AGENT_ID = "answer_synthesis"
    NAME = "Answer Synthesis Agent"
    RESPONSIBILITY = (
        "Synthesize a focused, evidence-grounded scientific answer from completed specialist "
        "results. Use only source passages included in the report, cite every factual claim, "
        "and abstain when the evidence is insufficient or only loosely related. Do not call "
        "tools or conduct new research."
    )
    ACCEPTED_STATUSES = frozenset(
        {
            InvestigationStatus.COMPLETED.value,
            InvestigationStatus.PARTIAL.value,
            InvestigationStatus.INSUFFICIENT_EVIDENCE.value,
        }
    )

    def __init__(self, *, answerer: Answerer) -> None:
        """Inject the existing grounded answerer to keep the synthesis agent testable."""
        if not isinstance(getattr(answerer, "model", None), str) or not answerer.model.strip():
            raise ValueError("answerer must expose a non-empty configured model identifier.")
        if not callable(getattr(answerer, "answer", None)):
            raise TypeError("answerer must expose an answer() method.")
        self._answerer = answerer

    @classmethod
    def from_environment(cls, project_root: Path = PROJECT_ROOT) -> "AnswerSynthesisAgent":
        """Create the agent using the existing configured Responses API settings."""
        return cls(answerer=OpenAIResponsesAnswerer.from_environment(project_root))

    def synthesize(self, report: Mapping[str, Any] | Any) -> SynthesisResult:
        """Synthesize an answer from a serialized investigation report or report object.

        Report objects must provide ``to_dict()``; the serialized form is the same format
        written by ``python -m exotrace.agents.investigate --save-json``.
        """
        payload = self._normalize_report(report)
        question = payload["question"].strip()
        status = payload["status"]
        if status not in self.ACCEPTED_STATUSES:
            raise AnswerSynthesisError(
                f"Cannot synthesize investigation with status {status!r}. "
                "Execute the plan first and provide a completed, partial, or "
                "insufficient-evidence report."
            )

        collected_evidence = self._collect_unique_evidence(payload)
        candidate_documents = [
            self._evidence_to_document(item) for item in collected_evidence
        ]
        # Reuse the existing provenance-driven selector before generation. It filters
        # mechanically derived association records only when the query does not ask
        # about that associated field/role. This relies on corpus metadata, not on
        # planet-specific facts or query-specific routing rules.
        selected_documents = select_answer_evidence(question, candidate_documents)
        selected_source_ids = {
            str(document.get("doc_id", "")) for document in selected_documents
        }
        evidence = tuple(
            item for item in collected_evidence if item.evidence_id in selected_source_ids
        )
        documents = [self._evidence_to_document(item) for item in evidence]
        try:
            answer = self._answerer.answer(
                question,
                documents,
                retrieval_strategy="agentic_synthesis",
                retrieval_scope="specialist_evidence",
                corpus_sha256=None,
            )
        except AnswerGenerationError as exc:
            raise AnswerSynthesisError(f"Grounded answer synthesis failed: {exc}") from exc
        except (TypeError, ValueError, KeyError) as exc:
            raise AnswerSynthesisError(f"Invalid synthesis input or response: {exc}") from exc

        return SynthesisResult(
            investigation_status=status,
            input_evidence_ids=tuple(item.evidence_id for item in evidence),
            answer=answer,
        )

    @staticmethod
    def _normalize_report(report: Mapping[str, Any] | Any) -> dict[str, Any]:
        """Accept the persisted JSON schema or an object exposing ``to_dict``."""
        if not isinstance(report, Mapping):
            to_dict = getattr(report, "to_dict", None)
            if not callable(to_dict):
                raise TypeError("report must be a mapping or expose to_dict().")
            report = to_dict()
        question = report.get("question")
        status = report.get("status")
        results = report.get("results")
        if not isinstance(question, str) or not question.strip():
            raise AnswerSynthesisError("Investigation report has no usable question.")
        if not isinstance(status, str) or not status.strip():
            raise AnswerSynthesisError("Investigation report has no usable status.")
        if not isinstance(results, list):
            raise AnswerSynthesisError("Investigation report results must be a list.")
        if any(not isinstance(item, Mapping) for item in results):
            raise AnswerSynthesisError("Every investigation result must be an object.")
        return {"question": question, "status": status, "results": results}

    @staticmethod
    def _collect_unique_evidence(report: Mapping[str, Any]) -> tuple[EvidenceReference, ...]:
        """Collect source evidence while rejecting conflicting reuse of an evidence ID."""
        unique: dict[str, EvidenceReference] = {}
        for result_index, result in enumerate(report["results"], start=1):
            raw_evidence = result.get("evidence", [])
            if not isinstance(raw_evidence, list):
                raise AnswerSynthesisError(
                    f"Investigation result {result_index} evidence must be a list."
                )
            for evidence_index, raw_item in enumerate(raw_evidence, start=1):
                if not isinstance(raw_item, Mapping):
                    raise AnswerSynthesisError(
                        f"Evidence item {result_index}:{evidence_index} must be an object."
                    )
                try:
                    item = EvidenceReference(
                        evidence_id=raw_item["evidence_id"],
                        source_id=raw_item["source_id"],
                        title=raw_item["title"],
                        excerpt=raw_item["excerpt"],
                        source_uri=raw_item.get("source_uri"),
                        source_kind=raw_item.get("source_kind"),
                        snapshot_id=raw_item.get("snapshot_id"),
                        record_id=raw_item.get("record_id"),
                        metadata=raw_item.get("metadata", {}),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise AnswerSynthesisError(
                        f"Malformed evidence item {result_index}:{evidence_index}: {exc}"
                    ) from exc

                existing = unique.get(item.evidence_id)
                if existing is None:
                    unique[item.evidence_id] = item
                elif not AnswerSynthesisAgent._same_source(existing, item):
                    raise AnswerSynthesisError(
                        f"Evidence ID {item.evidence_id!r} refers to conflicting source content."
                    )
        return tuple(unique.values())

    @staticmethod
    def _same_source(left: EvidenceReference, right: EvidenceReference) -> bool:
        """Compare source identity and content while ignoring retrieval-specific metadata."""
        return (
            left.source_id == right.source_id
            and left.title == right.title
            and left.excerpt == right.excerpt
            and left.source_uri == right.source_uri
            and left.source_kind == right.source_kind
            and left.snapshot_id == right.snapshot_id
            and left.record_id == right.record_id
        )

    @staticmethod
    def _evidence_to_document(item: EvidenceReference) -> dict[str, Any]:
        """Map one typed source reference to the existing answerer's document interface."""
        source_metadata = dict(item.metadata)
        nested_source_metadata = source_metadata.get("document_metadata")
        if isinstance(nested_source_metadata, Mapping):
            merged_metadata = dict(nested_source_metadata)
        else:
            merged_metadata = {}
        merged_metadata.update(
            {
                key: value
                for key, value in source_metadata.items()
                if key != "document_metadata"
            }
        )
        merged_metadata.update(
            {
                "source_url": item.source_uri,
                "source_type": item.source_kind,
                "snapshot_id": item.snapshot_id,
                "record_id": item.record_id,
                "source_file": merged_metadata.get("source_file")
                or merged_metadata.get("raw_file"),
            }
        )
        return {
            # Keep the originating evidence ID traceable through the generated E1, E2, ... ID.
            "doc_id": item.evidence_id,
            "title": item.title,
            "doc_type": item.source_kind or "specialist_source_evidence",
            "text": item.excerpt,
            "source_url": item.source_uri,
            "catalogue_record_id": item.record_id,
            "metadata": merged_metadata,
        }


def main(argv: list[str] | None = None) -> int:
    """Synthesize one saved investigation report and optionally persist answer JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to an investigation report written by exotrace.agents.investigate.",
    )
    parser.add_argument(
        "--save-json",
        type=Path,
        help="Optional path for the synthesized answer and source provenance JSON.",
    )
    args = parser.parse_args(argv)
    try:
        report_path = args.report
        if not report_path.is_absolute():
            report_path = PROJECT_ROOT / report_path
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report_payload, Mapping):
            raise AnswerSynthesisError("Investigation report JSON must contain an object.")
        agent = AnswerSynthesisAgent.from_environment(PROJECT_ROOT)
        result = agent.synthesize(report_payload)
        print(render_markdown(result.answer))
        if args.save_json:
            output_path = args.save_json
            if not output_path.is_absolute():
                output_path = PROJECT_ROOT / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"\nSynthesis JSON: {output_path}")
        return 0
    except (OSError, json.JSONDecodeError, TypeError, ValueError, AnswerSynthesisError) as exc:
        print(f"ERROR synthesizing ExoTrace answer: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
