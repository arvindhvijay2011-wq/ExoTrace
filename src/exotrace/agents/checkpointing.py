"""SQLite-backed checkpointing utilities for resumable ExoTrace LangGraph runs.

Persistent graph state is restricted to an explicit allowlist of ExoTrace contract classes.
Checkpoint files are local operational state, not scientific source-of-truth data.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from exotrace.agents.contracts import AgentResult, AgentStatus
from exotrace.agents.orchestrator import (
    InvestigationReport,
    InvestigationStatus,
)
from exotrace.agents.planning import InvestigationPlan, PlanDisposition, PlannedAgentTask
from exotrace.contracts import EvidenceReference, Finding


class CheckpointingError(RuntimeError):
    """Raised when a checkpoint thread cannot safely be created or resumed."""


class CheckpointingDependencyError(ImportError):
    """Raised when persistent checkpointing is requested without its optional package."""


_ALLOWED_CHECKPOINT_TYPES: tuple[type[Any], ...] = (
    AgentResult,
    AgentStatus,
    EvidenceReference,
    Finding,
    InvestigationPlan,
    InvestigationReport,
    InvestigationStatus,
    PlanDisposition,
    PlannedAgentTask,
)


def allowed_checkpoint_types() -> tuple[type[Any], ...]:
    """Return the exact application types permitted in persistent graph state."""
    return _ALLOWED_CHECKPOINT_TYPES


def validate_thread_id(thread_id: str) -> str:
    """Normalize and validate a portable LangGraph checkpoint thread ID."""
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id must be a non-empty string.")
    normalized = thread_id.strip()
    # Portable thread IDs should fit common persistent checkpoint backends.
    if len(normalized) > 255:
        raise ValueError("thread_id must not exceed 255 characters.")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("thread_id cannot contain control characters.")
    return normalized


def task_graph_thread_id(thread_id: str) -> str:
    """Derive a stable separate ID for nested task-graph checkpoints without exposing the input."""
    import hashlib

    normalized = validate_thread_id(thread_id)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"exotrace-task-graph-{digest}"


def _get_thread_checkpoint(checkpointer: Any, thread_id: str) -> Any | None:
    """Return the latest checkpoint for a thread through LangGraph's saver interface."""
    normalized = validate_thread_id(thread_id)
    return checkpointer.get_tuple({"configurable": {"thread_id": normalized}})


def ensure_fresh_thread(checkpointer: Any, thread_id: str) -> None:
    """Reject accidental reuse of a thread ID that already has checkpoint history."""
    if _get_thread_checkpoint(checkpointer, thread_id) is not None:
        raise CheckpointingError(
            f"Checkpoint thread {thread_id!r} already exists. Choose another --thread-id, "
            "or use --resume with the original question to continue an interrupted run."
        )


def load_resumable_plan(
    checkpointer: Any,
    thread_id: str,
    *,
    expected_question: str,
) -> InvestigationPlan:
    """Load a validated plan from an interrupted outer-graph checkpoint.

    A completed thread is never rerun by this helper. The question and plan are checked before
    the caller invokes the graph, so a thread cannot be silently repurposed for another query.
    """
    if not isinstance(expected_question, str) or not expected_question.strip():
        raise ValueError("expected_question must be a non-empty string.")
    snapshot = _get_thread_checkpoint(checkpointer, thread_id)
    if snapshot is None:
        raise CheckpointingError(
            f"No checkpoint exists for thread {thread_id!r}; there is nothing to resume."
        )

    checkpoint = getattr(snapshot, "checkpoint", None)
    if not isinstance(checkpoint, dict):
        raise CheckpointingError("The checkpoint record has an invalid structure.")
    channel_values = checkpoint.get("channel_values")
    if not isinstance(channel_values, dict):
        raise CheckpointingError("The checkpoint does not contain a valid graph state.")

    stored_question = channel_values.get("question")
    if not isinstance(stored_question, str) or stored_question.strip() != expected_question.strip():
        raise CheckpointingError(
            "The supplied question does not match the question stored in this checkpoint thread."
        )
    if channel_values.get("report") is not None:
        raise CheckpointingError(
            f"Checkpoint thread {thread_id!r} already has a final report and is complete; "
            "start a new thread for another investigation."
        )

    plan = channel_values.get("plan")
    if not isinstance(plan, InvestigationPlan):
        raise CheckpointingError(
            "The checkpoint has no restorable investigation plan. Start a new run instead."
        )
    if plan.question.strip() != expected_question.strip():
        raise CheckpointingError("The checkpoint plan does not match its stored question.")
    if plan.disposition is not PlanDisposition.READY:
        raise CheckpointingError(
            "Only interrupted READY plans can be resumed; this plan did not authorize execution."
        )
    return plan


@contextmanager
def open_sqlite_checkpointer(database_path: Path) -> Iterator[Any]:
    """Open a persistent SQLite saver with a precise allowlist of ExoTrace state classes.

    SQLite is suitable for local development and lightweight single-process use. A shared
    multi-worker deployment should use a production database-backed saver appropriate to its
    concurrency and operations requirements.
    """
    if not isinstance(database_path, Path):
        raise TypeError("database_path must be a pathlib.Path.")

    resolved_path = database_path.expanduser().resolve()
    if resolved_path.exists() and resolved_path.is_dir():
        raise ValueError(f"Checkpoint database path points to a directory: {resolved_path}")
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    # LangGraph recommends strict msgpack deserialization for checkpoint security. The explicit
    # serializer allowlist below permits only the typed ExoTrace contracts needed by our state.
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
    try:
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise CheckpointingDependencyError(
            "Persistent LangGraph checkpoints require the SQLite saver. Activate ExoTrace's "
            ".venv and run: python -m pip install -r requirements-langgraph.txt"
        ) from exc

    allowed_types = allowed_checkpoint_types()
    serializer = JsonPlusSerializer(
        allowed_json_modules=[(item.__module__, item.__name__) for item in allowed_types],
        allowed_msgpack_modules=allowed_types,
        pickle_fallback=False,
    )
    connection = sqlite3.connect(str(resolved_path), check_same_thread=False)
    try:
        checkpointer = SqliteSaver(connection, serde=serializer)
        yield checkpointer
    finally:
        connection.close()
