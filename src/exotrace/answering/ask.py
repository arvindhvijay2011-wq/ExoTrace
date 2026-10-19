"""Ask a scientific question using ExoTrace retrieval and grounded answer generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from exotrace.answering.evidence_selection import select_answer_evidence
from exotrace.answering.grounded_answer import (
    AnswerGenerationError,
    GroundedAnswer,
    OpenAIResponsesAnswerer,
    render_markdown,
)
from exotrace.vector.build_index import PROJECT_ROOT
from exotrace.vector.retrieve import (
    DEFAULT_RETRIEVAL_SCOPE,
    DEFAULT_RETRIEVAL_STRATEGY,
    VALID_SCOPES,
    VALID_STRATEGIES,
    HybridTextRetriever,
)


def answer_question(
    query: str,
    *,
    retriever: HybridTextRetriever,
    answerer: OpenAIResponsesAnswerer,
    top_k: int = 6,
    scope: str = DEFAULT_RETRIEVAL_SCOPE,
    strategy: str = DEFAULT_RETRIEVAL_STRATEGY,
) -> GroundedAnswer:
    """Retrieve evidence first, then generate a source-cited answer."""
    # Retrieve a wider pool so conservative filtering can remove redundant records
    # without unnecessarily reducing the number of documents sent to the answerer.
    retrieval_pool_size = max(top_k * 3, top_k + 5)
    retrieved = retriever.search(
        query,
        top_k=retrieval_pool_size,
        scope=scope,
        strategy=strategy,
    )
    selected_evidence = select_answer_evidence(query, retrieved, max_documents=top_k)
    corpus_sha = getattr(retriever, "corpus_sha256", None)
    return answerer.answer(
        query,
        selected_evidence,
        retrieval_strategy=strategy,
        retrieval_scope=scope,
        corpus_sha256=corpus_sha,
    )


def main() -> int:
    """CLI entry point for evidence-grounded question answering."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Question to answer from retrieved evidence.")
    parser.add_argument("--top-k", type=int, default=6, help="Number of retrieved documents to pass to the answerer.")
    parser.add_argument(
        "--scope",
        choices=tuple(sorted(VALID_SCOPES)),
        default=DEFAULT_RETRIEVAL_SCOPE,
        help="Explicit document scope. The default searches NASA references and source-derived definitions.",
    )
    parser.add_argument(
        "--strategy",
        choices=tuple(sorted(VALID_STRATEGIES)),
        default=DEFAULT_RETRIEVAL_STRATEGY,
        help="Explicit retrieval strategy. Dense is the current measured default.",
    )
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--save-json", type=Path, help="Optional path to save the answer and full provenance as JSON.")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")

    try:
        answerer = OpenAIResponsesAnswerer.from_environment(PROJECT_ROOT)
        retriever = HybridTextRetriever(device=args.device)
        result = answer_question(
            args.query,
            retriever=retriever,
            answerer=answerer,
            top_k=args.top_k,
            scope=args.scope,
            strategy=args.strategy,
        )
        print(render_markdown(result))
        if args.save_json:
            args.save_json.parent.mkdir(parents=True, exist_ok=True)
            args.save_json.write_text(
                json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"\nAnswer provenance JSON: {args.save_json}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, AnswerGenerationError) as exc:
        print(f"ERROR generating grounded answer: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR generating grounded answer: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
