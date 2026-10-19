"""Explicit-mode lexical and dense retrieval (BM25 + FAISS) for ExoTrace.

The caller explicitly selects retrieval strategy and document scope. Dense retrieval is
the documented default because it outperformed BM25 and RRF on the current 21-question
source-level benchmark; users can select BM25 or RRF for comparisons. No query-shape
heuristic silently changes the strategy or scope. Exact numeric answers and graph
traversal remain separate authoritative operations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from exotrace.vector.build_index import (
    CORPUS_MANIFEST_PATH,
    CORPUS_PATH,
    DEFAULT_MODEL,
    INDEX_MANIFEST_PATH,
    INDEX_PATH,
    PROJECT_ROOT,
)

# Preserve identifiers such as pl_orbeccen as single lexical tokens. Previously
# underscores split field codes into generic fragments and weakened exact lookup.
TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*(?:[.+/#'-][a-z0-9]+)*", re.IGNORECASE)
DEFAULT_RRF_K = 60
DEFAULT_RETRIEVAL_STRATEGY = "dense"
DEFAULT_RETRIEVAL_SCOPE = "references"
VALID_SCOPES = {"all", "references", "profiles"}
VALID_STRATEGIES = {"bm25", "dense", "rrf"}
REFERENCE_DOC_TYPE = "official_nasa_reference_chunk"
PARAMETER_DEFINITION_DOC_TYPE = "official_nasa_parameter_definition"
PROFILE_DOC_TYPE = "planet_profile"


def tokenize(text: str) -> list[str]:
    """Tokenize text while preserving underscore-delimited scientific identifiers."""
    return [token.casefold() for token in TOKEN_PATTERN.findall(text)]



def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, rrf_k: int = DEFAULT_RRF_K
) -> list[tuple[str, float]]:
    """Fuse ordered document-ID lists using reciprocal-rank fusion."""
    if rrf_k < 1:
        raise ValueError("rrf_k must be at least 1.")
    fused_scores: dict[str, float] = {}
    for ranking in rankings:
        seen_in_ranking: set[str] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if not doc_id or doc_id in seen_in_ranking:
                continue
            seen_in_ranking.add(doc_id)
            fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(fused_scores.items(), key=lambda item: (-item[1], item[0]))


def sha256_bytes(content: bytes) -> str:
    """Return a lowercase SHA-256 checksum."""
    return hashlib.sha256(content).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL and reject invalid or duplicate documents."""
    if not path.is_file():
        raise FileNotFoundError(f"Required vector corpus file does not exist: {path}")
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on corpus line {line_number}: {exc}") from exc
        doc_id = str(doc.get("doc_id", ""))
        if not doc_id or not str(doc.get("text", "")).strip():
            raise ValueError(f"Corpus line {line_number} needs non-empty doc_id and text.")
        if doc_id in seen:
            raise ValueError(f"Duplicate corpus doc_id: {doc_id}")
        seen.add(doc_id)
        docs.append(doc)
    if not docs:
        raise ValueError("Vector corpus is empty.")
    return docs


def allowed_doc_types(scope: str) -> set[str] | None:
    """Map a retrieval scope to document types; `None` means the entire corpus."""
    if scope == "all":
        return None
    if scope == "references":
        return {REFERENCE_DOC_TYPE, PARAMETER_DEFINITION_DOC_TYPE}
    if scope == "profiles":
        return {PROFILE_DOC_TYPE}
    raise ValueError(f"Unsupported retrieval scope: {scope!r}. Choose one of {sorted(VALID_SCOPES)}.")



class HybridTextRetriever:
    """Run the selected lexical, dense, or RRF strategy over a frozen corpus."""

    def __init__(
        self,
        *,
        corpus_path: Path | None = None,
        corpus_manifest_path: Path | None = None,
        index_path: Path | None = None,
        index_manifest_path: Path | None = None,
        model_name: str = DEFAULT_MODEL,
        device: str = "cpu",
    ) -> None:
        """Load and verify the frozen corpus, FAISS index, model, and BM25 index."""
        try:
            import faiss
            from rank_bm25 import BM25Okapi
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'Vector dependencies are missing. Run `python -m pip install -e ".[dev,vector]".'
            ) from exc

        self.corpus_path = corpus_path or (PROJECT_ROOT / CORPUS_PATH)
        self.corpus_manifest_path = corpus_manifest_path or (PROJECT_ROOT / CORPUS_MANIFEST_PATH)
        self.index_path = index_path or (PROJECT_ROOT / INDEX_PATH)
        self.index_manifest_path = index_manifest_path or (PROJECT_ROOT / INDEX_MANIFEST_PATH)

        if not self.corpus_manifest_path.is_file() or not self.index_manifest_path.is_file():
            raise FileNotFoundError(
                "Vector corpus/index manifest missing; run corpus and index build steps first."
            )

        self.corpus_manifest = json.loads(self.corpus_manifest_path.read_text(encoding="utf-8"))
        self.index_manifest = json.loads(self.index_manifest_path.read_text(encoding="utf-8"))
        self.corpus_sha256 = sha256_bytes(self.corpus_path.read_bytes())
        if self.corpus_sha256 != self.corpus_manifest.get("corpus_sha256"):
            raise ValueError("Vector corpus checksum differs from its manifest.")
        if self.corpus_sha256 != self.index_manifest.get("corpus_sha256"):
            raise ValueError("FAISS index was built from a different corpus checksum.")

        self.documents = _read_jsonl(self.corpus_path)
        if len(self.documents) != self.index_manifest.get("document_count"):
            raise ValueError("Corpus document count does not match the vector index manifest.")
        self.doc_index = {str(doc["doc_id"]): index for index, doc in enumerate(self.documents)}
        self.model_name = model_name
        manifest_model = str(self.index_manifest.get("embedding_model", ""))
        if model_name != manifest_model:
            raise ValueError(
                f"Requested model {model_name!r} differs from index model {manifest_model!r}; "
                "use the same model that built the index."
            )

        print("Loading local FAISS index and embedding model...")
        self.faiss_index = faiss.read_index(str(self.index_path))
        self.model = SentenceTransformer(model_name, device=device)
        expected_dimension = int(self.index_manifest["embedding_dimension"])
        actual_dimension = self.model.get_embedding_dimension()
        if actual_dimension != expected_dimension or self.faiss_index.d != expected_dimension:
            raise ValueError(
                f"Embedding dimension mismatch: model={actual_dimension}, "
                f"manifest={expected_dimension}, index={self.faiss_index.d}."
            )
        if self.faiss_index.ntotal != len(self.documents):
            raise ValueError("FAISS vector count does not match corpus document count.")

        tokenized = [tokenize(str(doc["text"])) for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized)
        self._doc_types = [str(document.get("doc_type") or "") for document in self.documents]
        print(f"Hybrid text retriever ready: {len(self.documents):,} documents.")

    def rank_channels(
        self,
        query: str,
        *,
        candidate_k: int = 30,
        scope: str = "all",
    ) -> dict[str, list[str]]:
        """Return independently ranked BM25, dense, and RRF candidates within the scope."""
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Query cannot be empty.")
        if candidate_k < 1:
            raise ValueError("candidate_k must be at least 1.")
        allowed_types = allowed_doc_types(scope)
        eligible_indices = [
            index
            for index, doc_type in enumerate(self._doc_types)
            if allowed_types is None or doc_type in allowed_types
        ]
        if not eligible_indices:
            raise ValueError(f"No documents exist for retrieval scope {scope!r}.")

        lexical_scores = np.asarray(
            self.bm25.get_scores(tokenize(normalized_query)), dtype=np.float64
        )
        lexical_order = sorted(
            eligible_indices,
            key=lambda index: (-float(lexical_scores[index]), index),
        )
        lexical_ids: list[str] = []
        for index_value in lexical_order:
            score = float(lexical_scores[index_value])
            if score <= 0.0:
                break
            lexical_ids.append(str(self.documents[index_value]["doc_id"]))
            if len(lexical_ids) >= candidate_k:
                break

        query_vector = self.model.encode(
            [normalized_query], convert_to_numpy=True, normalize_embeddings=True
        )
        query_vector = np.ascontiguousarray(np.asarray(query_vector, dtype=np.float32))
        # Search the complete index when filtering by doc type, then retain the nearest
        # eligible candidates. The corpus is only ~6.5k items, so this remains inexpensive
        # and avoids a dense-index top-k filled with irrelevant document types.
        dense_search_k = self.faiss_index.ntotal if scope != "all" else min(
            candidate_k, self.faiss_index.ntotal
        )
        _dense_scores, dense_indices = self.faiss_index.search(query_vector, dense_search_k)
        eligible_index_set = set(eligible_indices)
        dense_ids: list[str] = []
        for index_value in dense_indices[0]:
            index_int = int(index_value)
            if index_int < 0 or index_int not in eligible_index_set:
                continue
            dense_ids.append(str(self.documents[index_int]["doc_id"]))
            if len(dense_ids) >= candidate_k:
                break

        fused_ids = [
            doc_id
            for doc_id, _score in reciprocal_rank_fusion([lexical_ids, dense_ids])
        ]
        return {
            "bm25": lexical_ids,
            "dense": dense_ids,
            "rrf": fused_ids,
        }

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        candidate_k: int | None = None,
        scope: str = DEFAULT_RETRIEVAL_SCOPE,
        strategy: str = DEFAULT_RETRIEVAL_STRATEGY,
    ) -> list[dict[str, Any]]:
        """Return scoped results from an explicitly selected retrieval strategy.

        Dense retrieval is the documented default based on the current benchmark. Use
        ``strategy="bm25"`` or ``strategy="rrf"`` to compare alternate approaches.
        Choose ``scope="profiles"`` for catalogue profiles or ``scope="all"`` for all
        document types; no query-text heuristic silently changes these choices.
        """
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Query cannot be empty.")
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"Unsupported strategy {strategy!r}. Choose one of {sorted(VALID_STRATEGIES)}.")
        selected_strategy = strategy
        retrieve_k = candidate_k if candidate_k is not None else max(30, top_k * 5)
        if retrieve_k < top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k.")

        allowed_types = allowed_doc_types(scope)
        eligible_indices = [
            index
            for index, doc_type in enumerate(self._doc_types)
            if allowed_types is None or doc_type in allowed_types
        ]
        if not eligible_indices:
            raise ValueError(f"No documents exist for retrieval scope {scope!r}.")
        retrieve_k = min(retrieve_k, len(eligible_indices))

        lexical_scores = np.asarray(
            self.bm25.get_scores(tokenize(normalized_query)), dtype=np.float64
        )
        lexical_order = sorted(
            eligible_indices,
            key=lambda index: (-float(lexical_scores[index]), index),
        )
        lexical_ids: list[str] = []
        lexical_score_by_id: dict[str, float] = {}
        for index_value in lexical_order:
            score = float(lexical_scores[index_value])
            if score <= 0.0:
                break
            doc_id = str(self.documents[index_value]["doc_id"])
            lexical_ids.append(doc_id)
            lexical_score_by_id[doc_id] = score
            if len(lexical_ids) >= retrieve_k:
                break

        query_vector = self.model.encode(
            [normalized_query], convert_to_numpy=True, normalize_embeddings=True
        )
        query_vector = np.ascontiguousarray(np.asarray(query_vector, dtype=np.float32))
        dense_search_k = self.faiss_index.ntotal if scope != "all" else min(
            retrieve_k, self.faiss_index.ntotal
        )
        dense_scores, dense_indices = self.faiss_index.search(query_vector, dense_search_k)
        eligible_index_set = set(eligible_indices)
        dense_ids: list[str] = []
        dense_score_by_id: dict[str, float] = {}
        for score, item_index in zip(dense_scores[0], dense_indices[0], strict=True):
            index_value = int(item_index)
            if index_value < 0 or index_value not in eligible_index_set:
                continue
            doc_id = str(self.documents[index_value]["doc_id"])
            dense_ids.append(doc_id)
            dense_score_by_id[doc_id] = float(score)
            if len(dense_ids) >= retrieve_k:
                break

        lexical_rank = {doc_id: rank for rank, doc_id in enumerate(lexical_ids, start=1)}
        dense_rank = {doc_id: rank for rank, doc_id in enumerate(dense_ids, start=1)}
        fused_with_scores = reciprocal_rank_fusion([lexical_ids, dense_ids])
        fused_score_by_id = dict(fused_with_scores)
        fused_ids = [doc_id for doc_id, _score in fused_with_scores]
        selected_ids_by_strategy = {
            "bm25": lexical_ids,
            "dense": dense_ids,
            "rrf": fused_ids,
        }
        selected_ids = selected_ids_by_strategy[selected_strategy][:top_k]
        docs_by_id = {str(doc["doc_id"]): doc for doc in self.documents}

        results: list[dict[str, Any]] = []
        for rank, doc_id in enumerate(selected_ids, start=1):
            document = dict(docs_by_id[doc_id])
            selected_score: float | None
            if selected_strategy == "bm25":
                selected_score = lexical_score_by_id.get(doc_id)
            elif selected_strategy == "dense":
                selected_score = dense_score_by_id.get(doc_id)
            else:
                selected_score = fused_score_by_id.get(doc_id)
            document["retrieval"] = {
                "scope": scope,
                "strategy": selected_strategy,
                "selected_rank": rank,
                "selected_score": selected_score,
                "rrf_score": fused_score_by_id.get(doc_id),
                "bm25_rank": lexical_rank.get(doc_id),
                "bm25_score": lexical_score_by_id.get(doc_id),
                "dense_rank": dense_rank.get(doc_id),
                "dense_similarity": dense_score_by_id.get(doc_id),
                "channels": [
                    channel
                    for channel, ranks in (("bm25", lexical_rank), ("faiss_dense", dense_rank))
                    if doc_id in ranks
                ],
            }
            results.append(document)
        return results


def main() -> int:
    """Run one local retrieval query using explicit strategy and scope settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Natural-language query to search.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to print.")
    parser.add_argument(
        "--candidate-k", type=int, default=30, help="Candidates to retrieve per channel."
    )
    parser.add_argument(
        "--strategy",
        choices=tuple(sorted(VALID_STRATEGIES)),
        default=DEFAULT_RETRIEVAL_STRATEGY,
        help="Retrieval strategy. Dense is the current benchmark-supported default; BM25 and RRF are explicit alternatives.",
    )
    parser.add_argument(
        "--scope",
        choices=tuple(sorted(VALID_SCOPES)),
        default=DEFAULT_RETRIEVAL_SCOPE,
        help="Document scope. Defaults to NASA references and source-derived definitions; use profiles or all explicitly when needed.",
    )
    parser.add_argument(
        "--device", choices=("cpu", "cuda"), default="cpu", help="Query embedding device."
    )
    args = parser.parse_args()

    try:
        retriever = HybridTextRetriever(device=args.device)
        scope = args.scope
        results = retriever.search(
            args.query,
            top_k=args.top_k,
            candidate_k=max(args.candidate_k, args.top_k),
            scope=scope,
            strategy=args.strategy,
        )
        selected_strategy = results[0]["retrieval"]["strategy"] if results else args.strategy
        print(f"\nQuery: {args.query}")
        print(f"Retrieval scope: {scope}")
        print(f"Retrieval strategy: {selected_strategy}")
        print(f"Results: {len(results)}")
        for rank, result in enumerate(results, start=1):
            metadata = result.get("metadata") or {}
            print(
                f"\n[{rank}] {result.get('title') or result['doc_id']} "
                f"({result.get('doc_type')})"
            )
            print(f"  doc_id: {result['doc_id']}")
            if metadata.get("source_url"):
                print(f"  source: {metadata['source_url']}")
            if metadata.get("record_id"):
                print(f"  catalogue_record_id: {metadata['record_id']}")
            if metadata.get("planet_name"):
                print(
                    f"  planet: {metadata['planet_name']} | host: {metadata.get('hostname')}"
                )
            retrieval = result["retrieval"]
            print(
                "  selected_score={} | RRF={} | BM25 rank={} | dense rank={} | channels={}".format(
                    (f"{retrieval['selected_score']:.6f}" if retrieval["selected_score"] is not None else "n/a"),
                    (f"{retrieval['rrf_score']:.6f}" if retrieval["rrf_score"] is not None else "n/a"),
                    retrieval["bm25_rank"],
                    retrieval["dense_rank"],
                    ",".join(retrieval["channels"]),
                )
            )
            excerpt = " ".join(str(result["text"]).split())
            print(f"  excerpt: {excerpt[:500]}{'...' if len(excerpt) > 500 else ''}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR during hybrid retrieval: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
