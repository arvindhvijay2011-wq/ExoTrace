"""Evaluate BM25, dense, and RRF retrieval on a fixed source-level benchmark.

Relevance labels identify NASA source pages, not exact passages. Both ordinary reference
chunks and source-derived parameter-definition documents count as originating from their
NASA page. This measures source discovery and ranking, not answer correctness.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


from exotrace.vector.retrieve import PROJECT_ROOT, HybridTextRetriever

DEFAULT_BENCHMARK_PATH = Path("data/evaluation/retrieval_benchmark.json")
DEFAULT_REPORT_JSON = Path("data/manifests/retrieval_benchmark_report.json")
DEFAULT_REPORT_CSV = Path("data/manifests/retrieval_benchmark_report.csv")


def source_slug(doc_id: str) -> str | None:
    """Return the NASA source slug for chunks and source-derived field documents."""
    parts = doc_id.split(":")
    if len(parts) >= 4 and parts[0] == "reference" and parts[2] == "chunk":
        return parts[1]
    return None


def first_relevant_rank(
    ranked_ids: Sequence[str], expected_source_slugs: set[str]
) -> int | None:
    """Find the first one-based rank from an expected source page."""
    for rank, doc_id in enumerate(ranked_ids, start=1):
        if source_slug(doc_id) in expected_source_slugs:
            return rank
    return None


def reciprocal_rank_at_k(rank: int | None, k: int) -> float:
    """Compute reciprocal rank truncated at k."""
    if k < 1:
        raise ValueError("k must be at least 1.")
    return 1.0 / rank if rank is not None and 1 <= rank <= k else 0.0


def hit_at_k(rank: int | None, k: int) -> int:
    """Return 1 when a relevant source occurs in the first k results."""
    if k < 1:
        raise ValueError("k must be at least 1.")
    return int(rank is not None and 1 <= rank <= k)


def load_benchmark(path: Path) -> list[dict[str, Any]]:
    """Load and validate benchmark question definitions."""
    if not path.is_file():
        raise FileNotFoundError(f"Benchmark file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Benchmark must contain a non-empty 'questions' list.")
    seen_ids: set[str] = set()
    for item in questions:
        if not isinstance(item, dict):
            raise ValueError("Each benchmark question must be an object.")
        question_id = str(item.get("id", "")).strip()
        query = str(item.get("query", "")).strip()
        expected = item.get("expected_source_slugs")
        if not question_id or not query or not isinstance(expected, list) or not expected:
            raise ValueError(
                "Each question needs non-empty id/query and expected_source_slugs."
            )
        if question_id in seen_ids:
            raise ValueError(f"Duplicate benchmark question ID: {question_id}")
        seen_ids.add(question_id)
    return questions


def _rank_channels(
    retriever: HybridTextRetriever, query: str, *, candidate_k: int
) -> dict[str, list[str]]:
    """Rank NASA reference chunks and source-derived parameter definitions.

    Generated planet profiles are excluded because benchmark relevance labels identify
    official NASA source-page slugs. Parameter-definition docs retain the same source slug
    in their canonical document ID and are eligible for the same labels.
    """
    return retriever.rank_channels(query, candidate_k=candidate_k, scope="references")


def _validate_expected_sources(
    questions: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> None:
    """Ensure every gold source slug exists in the frozen corpus."""
    available = {slug for doc in documents if (slug := source_slug(str(doc["doc_id"]))) is not None}
    missing = sorted(
        {
            str(slug)
            for question in questions
            for slug in question["expected_source_slugs"]
            if str(slug) not in available
        }
    )
    if missing:
        raise ValueError(f"Benchmark refers to source slugs absent from corpus: {missing}")


def evaluate_benchmark(
    questions: list[dict[str, Any]],
    retriever: HybridTextRetriever,
    *,
    candidate_k: int = 50,
    metric_k: int = 5,
) -> dict[str, Any]:
    """Evaluate retrieval-channel ranking over the fixed source-level benchmark."""
    if candidate_k < metric_k or metric_k < 1:
        raise ValueError("Require candidate_k >= metric_k >= 1.")
    _validate_expected_sources(questions, retriever.documents)

    per_question: list[dict[str, Any]] = []
    channels = ("bm25", "dense", "rrf")
    accumulators: dict[str, dict[str, float]] = {
        channel: defaultdict(float) for channel in channels
    }
    for question in questions:
        expected = {str(slug) for slug in question["expected_source_slugs"]}
        rankings = _rank_channels(retriever, str(question["query"]), candidate_k=candidate_k)
        entry: dict[str, Any] = {
            "id": question["id"],
            "query": question["query"],
            "expected_source_slugs": sorted(expected),
            "note": question.get("note", ""),
            "channels": {},
        }
        for channel in channels:
            ranked_ids = rankings[channel]
            relevant_rank = first_relevant_rank(ranked_ids, expected)
            hit = hit_at_k(relevant_rank, metric_k)
            reciprocal_rank = reciprocal_rank_at_k(relevant_rank, metric_k)
            accumulators[channel]["hit_at_k"] += hit
            accumulators[channel]["mrr_at_k"] += reciprocal_rank
            entry["channels"][channel] = {
                f"first_relevant_rank": relevant_rank,
                f"hit_at_{metric_k}": hit,
                f"reciprocal_rank_at_{metric_k}": reciprocal_rank,
                "top_doc_ids": ranked_ids[:metric_k],
                "top_source_slugs": [source_slug(doc_id) for doc_id in ranked_ids[:metric_k]],
            }
        per_question.append(entry)

    count = len(questions)
    summary = {
        channel: {
            f"hit_at_{metric_k}": round(values["hit_at_k"] / count, 4),
            f"mrr_at_{metric_k}": round(values["mrr_at_k"] / count, 4),
        }
        for channel, values in accumulators.items()
    }
    return {
        "project": "ExoTrace",
        "benchmark_type": "source_level_retrieval_baseline_comparison",
        "retrieval_scope": "official_nasa_reference_chunks_and_source_derived_parameter_definitions",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "question_count": count,
        "candidate_k": candidate_k,
        "metric_k": metric_k,
        "corpus_sha256": retriever.corpus_sha256,
        "index_manifest": str(retriever.index_manifest_path.relative_to(PROJECT_ROOT)),
        "relevance_definition": (
            "The benchmark searches official NASA reference chunks and source-derived parameter-definition "
            "documents. A result is considered relevant if its source-page slug matches one of the gold slugs. "
            "Generated planet profiles are excluded. This is source-level rather than passage-level relevance "
            "and does not measure answer correctness."
        ),
        "summary": summary,
        "results": per_question,
    }


def write_report(report: dict[str, Any], *, json_path: Path, csv_path: Path) -> None:
    """Write machine-readable JSON and convenient row-per-channel CSV reports."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    fields = [
        "id", "query", "channel", "expected_source_slugs", "first_relevant_rank",
        "hit_at_k", "reciprocal_rank_at_k", "top_doc_ids", "top_source_slugs", "note",
    ]
    metric_k = int(report["metric_k"])
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in report["results"]:
            for channel, values in result["channels"].items():
                writer.writerow(
                    {
                        "id": result["id"],
                        "query": result["query"],
                        "channel": channel,
                        "expected_source_slugs": ";".join(result["expected_source_slugs"]),
                        "first_relevant_rank": values["first_relevant_rank"],
                        "hit_at_k": values[f"hit_at_{metric_k}"],
                        "reciprocal_rank_at_k": values[f"reciprocal_rank_at_{metric_k}"],
                        "top_doc_ids": ";".join(values["top_doc_ids"]),
                        "top_source_slugs": ";".join(str(s) for s in values["top_source_slugs"]),
                        "note": result["note"],
                    }
                )


def main() -> int:
    """CLI entry point for baseline retrieval evaluation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--metric-k", type=int, default=5)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--benchmark", type=Path, default=PROJECT_ROOT / DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--report-json", type=Path, default=PROJECT_ROOT / DEFAULT_REPORT_JSON)
    parser.add_argument("--report-csv", type=Path, default=PROJECT_ROOT / DEFAULT_REPORT_CSV)
    args = parser.parse_args()
    try:
        questions = load_benchmark(args.benchmark)
        retriever = HybridTextRetriever(device=args.device)
        report = evaluate_benchmark(
            questions, retriever, candidate_k=args.candidate_k, metric_k=args.metric_k
        )
        write_report(report, json_path=args.report_json, csv_path=args.report_csv)
        print(f"\nBenchmark questions: {report['question_count']}")
        print(f"Metric: Hit@{args.metric_k} and MRR@{args.metric_k} (source-level labels)")
        print("Evaluation scope: NASA reference chunks + source-derived parameter definitions (source-level labels)")
        print("Retrieval modes are evaluated independently; no automatic query-shape routing is applied.")
        for channel, metrics in report["summary"].items():
            print(
                f"  {channel.upper():5s} | Hit@{args.metric_k}={metrics[f'hit_at_{args.metric_k}']:.3f} "
                f"| MRR@{args.metric_k}={metrics[f'mrr_at_{args.metric_k}']:.3f}"
            )
        for result in report["results"]:
            print(f"\n[{result['id']}] {result['query']}")
            for channel in ("bm25", "dense", "rrf"):
                values = result["channels"][channel]
                print(
                    f"  {channel.upper():5s}: first relevant rank={values['first_relevant_rank']}; "
                    f"top sources={values['top_source_slugs']}"
                )
        print(f"\nJSON report: {args.report_json}")
        print(f"CSV report:  {args.report_csv}")
        print("Interpretation: compare channels; do not treat this small source-level benchmark as final quality proof.")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR evaluating retrieval: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR evaluating retrieval: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
