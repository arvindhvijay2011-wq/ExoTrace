"""Read-only adapter from the existing ExoTrace vector retriever to tool contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from exotrace.contracts import EvidenceReference
from exotrace.tools.contracts import ToolDescriptor, ToolRequest, ToolResult, ToolStatus


class SearchRetriever(Protocol):
    """Minimum retriever interface required by the literature search tool."""

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        scope: str = "references",
        strategy: str = "dense",
    ) -> list[dict[str, Any]]:
        """Return ranked documents from the configured frozen retrieval corpus."""
        ...


@dataclass(frozen=True, slots=True)
class LiteratureSearchConfig:
    """Operational settings for reference retrieval.

    The reference scope is a deliberate permission boundary for this specialist tool. The
    strategy and result budgets are configurable and do not depend on query wording.
    """

    strategy: str = "dense"
    default_top_k: int = 6
    max_top_k: int = 30

    def __post_init__(self) -> None:
        """Validate the configured retrieval behavior and bounds."""
        if not isinstance(self.strategy, str) or not self.strategy.strip():
            raise ValueError("strategy must be a non-empty string.")
        if (
            isinstance(self.default_top_k, bool)
            or not isinstance(self.default_top_k, int)
            or isinstance(self.max_top_k, bool)
            or not isinstance(self.max_top_k, int)
        ):
            raise TypeError("Retrieval result limits must be integers.")
        if self.default_top_k < 1:
            raise ValueError("default_top_k must be a positive integer.")
        if self.max_top_k < self.default_top_k:
            raise ValueError("max_top_k must be an integer at least default_top_k.")


class LiteratureSearchTool:
    """Search the existing frozen text corpus, restricted to reference documents."""

    TOOL_ID = "literature.search"

    def __init__(
        self,
        retriever: SearchRetriever,
        *,
        config: LiteratureSearchConfig | None = None,
    ) -> None:
        """Wrap an already-configured retriever without loading another model or index."""
        self._retriever = retriever
        self._config = config or LiteratureSearchConfig()

    @property
    def descriptor(self) -> ToolDescriptor:
        """Expose the schema and purpose to agents without exposing executable internals."""
        return ToolDescriptor(
            tool_id=self.TOOL_ID,
            name="Literature and definition search",
            purpose=(
                "Retrieve source passages and parameter definitions from the configured "
                "reference corpus. This tool cannot search planet profiles or modify data."
            ),
            capabilities=("literature.retrieve", "source.reference_search"),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "top_k": {"type": "integer", "minimum": 1},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "returned_count": {"type": "integer", "minimum": 0},
                    "scope": {"type": "string"},
                    "strategy": {"type": "string"},
                    "corpus_sha256": {"type": ["string", "null"]},
                },
            },
            read_only=True,
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        """Run one reference search and preserve each document's source metadata."""
        if request.tool_id != self.TOOL_ID:
            return self._failure(request, "wrong_tool_id", "Request tool ID does not match.")

        arguments = dict(request.arguments)
        unsupported = sorted(set(arguments) - {"query", "top_k"})
        if unsupported:
            return self._failure(
                request,
                "unsupported_arguments",
                f"Unsupported literature search arguments: {unsupported}.",
            )

        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return self._failure(request, "invalid_query", "query must be a non-empty string.")

        top_k = arguments.get("top_k", self._config.default_top_k)
        if isinstance(top_k, bool) or not isinstance(top_k, int):
            return self._failure(request, "invalid_top_k", "top_k must be an integer.")
        if top_k < 1 or top_k > self._config.max_top_k:
            return self._failure(
                request,
                "invalid_top_k",
                f"top_k must be between 1 and {self._config.max_top_k}.",
            )

        try:
            documents = self._retriever.search(
                query.strip(),
                top_k=top_k,
                scope="references",
                strategy=self._config.strategy,
            )
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            return self._failure(request, "retrieval_failed", str(exc))

        evidence: list[EvidenceReference] = []
        seen_ids: set[str] = set()
        malformed_count = 0
        for document in documents:
            if not isinstance(document, Mapping):
                malformed_count += 1
                continue

            doc_id = str(document.get("doc_id", "")).strip()
            excerpt = str(document.get("text", "")).strip()
            if not doc_id or not excerpt:
                malformed_count += 1
                continue

            evidence_id = f"literature:{doc_id}"
            if evidence_id in seen_ids:
                malformed_count += 1
                continue
            seen_ids.add(evidence_id)

            raw_metadata = document.get("metadata")
            metadata: dict[str, Any] = (
                dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
            )
            retrieval = document.get("retrieval")
            retrieval_data = dict(retrieval) if isinstance(retrieval, Mapping) else {}
            source_url = metadata.get("source_url")
            source_uri = (
                source_url.strip()
                if isinstance(source_url, str) and source_url.strip()
                else None
            )
            source_kind = document.get("doc_type")
            source_kind_value = (
                source_kind.strip()
                if isinstance(source_kind, str) and source_kind.strip()
                else "reference_document"
            )
            record_id = metadata.get("record_id")
            record_id_value = (
                str(record_id).strip()
                if record_id is not None and str(record_id).strip()
                else None
            )
            snapshot_id = metadata.get("snapshot_id")
            if not snapshot_id:
                corpus_manifest = getattr(self._retriever, "corpus_manifest", {})
                if isinstance(corpus_manifest, Mapping):
                    snapshot_id = corpus_manifest.get("snapshot_id")
            snapshot_id_value = (
                str(snapshot_id).strip()
                if snapshot_id is not None and str(snapshot_id).strip()
                else None
            )

            try:
                evidence.append(
                    EvidenceReference(
                        evidence_id=evidence_id,
                        source_id=doc_id,
                        title=str(document.get("title") or doc_id),
                        excerpt=excerpt,
                        source_uri=source_uri,
                        source_kind=source_kind_value,
                        snapshot_id=snapshot_id_value,
                        record_id=record_id_value,
                        metadata={
                            "doc_type": source_kind_value,
                            "document_metadata": metadata,
                            "retrieval": retrieval_data,
                        },
                    )
                )
            except (TypeError, ValueError):
                malformed_count += 1

        retrieval_data = {
            "requested_query": query.strip(),
            "requested_top_k": top_k,
            "returned_count": len(evidence),
            "scope": "references",
            "strategy": self._config.strategy,
            "corpus_sha256": getattr(self._retriever, "corpus_sha256", None),
            "malformed_documents_skipped": malformed_count,
        }
        status = ToolStatus.PARTIAL if malformed_count else ToolStatus.SUCCEEDED
        message = (
            f"Skipped {malformed_count} malformed or duplicate retrieval result(s)."
            if malformed_count
            else None
        )
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=status,
            data=retrieval_data,
            evidence=tuple(evidence),
            message=message,
        )

    def _failure(self, request: ToolRequest, code: str, message: str) -> ToolResult:
        """Create a structured tool failure without leaking an exception traceback."""
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.FAILED,
            data={},
            message=message,
            error_code=code,
        )
