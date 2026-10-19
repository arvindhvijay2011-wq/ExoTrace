"""Build a FAISS cosine-similarity index over the fixed ExoTrace text corpus."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CORPUS_PATH = Path("data/processed/vector_corpus.jsonl")
CORPUS_MANIFEST_PATH = Path("data/manifests/vector_corpus_manifest.json")
INDEX_PATH = Path("data/processed/vector_index/exotrace.faiss")
INDEX_MANIFEST_PATH = Path("data/manifests/vector_index_manifest.json")
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def sha256_bytes(content: bytes) -> str:
    """Return a lowercase SHA-256 checksum."""
    return hashlib.sha256(content).hexdigest()


def _read_corpus(path: Path) -> list[dict[str, Any]]:
    """Read and minimally validate the JSONL corpus."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Vector corpus not found: {path}. Run `python -m exotrace.vector.build_corpus` first."
        )
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in corpus on line {line_number}: {exc}") from exc
        doc_id = str(doc.get("doc_id", ""))
        text = str(doc.get("text", "")).strip()
        if not doc_id or not text:
            raise ValueError(f"Corpus line {line_number} requires non-empty doc_id and text.")
        if doc_id in seen_ids:
            raise ValueError(f"Duplicate document ID in corpus: {doc_id}")
        seen_ids.add(doc_id)
        documents.append(doc)
    if not documents:
        raise ValueError("Vector corpus has no documents.")
    return documents


def _version(package_name: str) -> str | None:
    """Return an installed package version if available."""
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def build_faiss_index(
    *,
    model_name: str = DEFAULT_MODEL,
    device: str = "cpu",
    force: bool = False,
) -> dict[str, Any]:
    """Embed the corpus and write a normalized-vector inner-product FAISS index."""
    corpus_path = PROJECT_ROOT / CORPUS_PATH
    corpus_manifest_path = PROJECT_ROOT / CORPUS_MANIFEST_PATH
    index_path = PROJECT_ROOT / INDEX_PATH
    manifest_path = PROJECT_ROOT / INDEX_MANIFEST_PATH

    if (index_path.exists() or manifest_path.exists()) and not force:
        raise FileExistsError(
            f"Vector index already exists at {index_path}. Use --force only after intentionally "
            "changing the corpus/model and wanting to replace the index."
        )
    if not corpus_manifest_path.is_file():
        raise FileNotFoundError(f"Vector corpus manifest not found: {corpus_manifest_path}")

    corpus_sha = sha256_bytes(corpus_path.read_bytes())
    corpus_manifest = json.loads(corpus_manifest_path.read_text(encoding="utf-8"))
    if corpus_manifest.get("corpus_sha256") != corpus_sha:
        raise ValueError("Vector corpus checksum does not match its manifest; refusing to index.")

    try:
        import faiss
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            'Vector dependencies are missing. Run `python -m pip install -e ".[dev,vector]"`.'
        ) from exc

    documents = _read_corpus(corpus_path)
    texts = [str(doc["text"]) for doc in documents]
    print(f"Loading embedding model: {model_name} (device={device})")
    model = SentenceTransformer(model_name, device=device)
    dimension = model.get_embedding_dimension()
    if dimension is None or dimension < 1:
        raise RuntimeError("Embedding model did not report a valid embedding dimension.")

    embeddings = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    vectors = np.ascontiguousarray(np.asarray(embeddings, dtype=np.float32))
    if vectors.shape != (len(documents), int(dimension)):
        raise RuntimeError(
            f"Embedding shape {vectors.shape} did not match expected "
            f"({len(documents)}, {dimension})."
        )
    if not np.isfinite(vectors).all():
        raise ValueError("Embedding matrix contains non-finite values.")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_index_path = index_path.with_name(index_path.name + ".tmp")
    index = faiss.IndexFlatIP(int(dimension))
    index.add(vectors)
    faiss.write_index(index, str(temp_index_path))
    temp_index_path.replace(index_path)

    manifest: dict[str, Any] = {
        "project": "ExoTrace",
        "built_at_utc": datetime.now(UTC).isoformat(),
        "index_file": INDEX_PATH.as_posix(),
        "index_type": "faiss.IndexFlatIP",
        "distance_semantics": (
            "Inner product over L2-normalized vectors; equivalent to cosine similarity."
        ),
        "normalized_embeddings": True,
        "embedding_model": model_name,
        "embedding_dimension": int(dimension),
        "document_count": len(documents),
        "index_vector_count": int(index.ntotal),
        "corpus_file": CORPUS_PATH.as_posix(),
        "corpus_sha256": corpus_sha,
        "catalogue_snapshot_id": corpus_manifest.get("snapshot_id"),
        "catalogue_source_sha256": corpus_manifest.get("catalogue_source_sha256"),
        "python_version": platform.python_version(),
        "faiss_cpu_version": _version("faiss-cpu"),
        "sentence_transformers_version": _version("sentence-transformers"),
        "numpy_version": _version("numpy"),
        "device_used_for_build": device,
        "notes": [
            "The corpus and model identifier are recorded for reproducibility.",
            "Exact numerical questions must use source-linked structured catalogue records, "
            "not vector similarity.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Documents embedded: {len(documents):,}")
    print(f"Embedding dimension: {dimension}")
    print(f"FAISS vectors: {index.ntotal:,}")
    print(f"Corpus SHA-256 verified: {corpus_sha}")
    print(f"Index: {INDEX_PATH.as_posix()}")
    print(f"Manifest: {INDEX_MANIFEST_PATH.as_posix()}")
    return manifest


def main() -> int:
    """CLI entry point for vector index creation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help="SentenceTransformer model identifier."
    )
    parser.add_argument(
        "--device", choices=("cpu", "cuda"), default="cpu", help="Embedding device."
    )
    parser.add_argument(
        "--force", action="store_true", help="Replace the existing index and manifest."
    )
    args = parser.parse_args()
    try:
        build_faiss_index(model_name=args.model, device=args.device, force=args.force)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR building FAISS index: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
