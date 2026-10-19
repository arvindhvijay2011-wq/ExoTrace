"""Specialist that retrieves literature passages and source-derived definitions."""

from __future__ import annotations

from typing import Any

from exotrace.agents._support import validate_specialist_task
from exotrace.agents.contracts import (
    AgentDescriptor,
    AgentResult,
    AgentStatus,
    AgentTask,
    SpecialistAgent,
)
from exotrace.contracts import EvidenceReference, Finding
from exotrace.tools.contracts import ToolExecutor, ToolRequest, ToolStatus
from exotrace.tools.literature_search import LiteratureSearchTool


class LiteratureDefinitionAgent:
    """Find directly relevant reference passages without writing a scientific answer.

    The agent performs one bounded retrieval call. It does not summarize retrieved sources,
    look up catalogue values, perform calculations, or select other agents. Those tasks
    belong to other specialists and the future orchestrator.
    """

    AGENT_ID = "literature_definition"
    TOOL_ID = LiteratureSearchTool.TOOL_ID

    @property
    def descriptor(self) -> AgentDescriptor:
        """Declare the specialist's narrow responsibility and sole permitted tool."""
        return AgentDescriptor(
            agent_id=self.AGENT_ID,
            name="Literature and Definition Agent",
            responsibility=(
                "Retrieve relevant passages and parameter definitions from the frozen "
                "reference corpus and preserve their source provenance. Do not interpret "
                "measurements or compose a final scientific answer."
            ),
            capabilities=(
                "literature.retrieve",
                "source.reference_search",
                "parameter.definition",
            ),
            allowed_tool_ids=(self.TOOL_ID,),
        )

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        """Retrieve references for an explicitly assigned task and return source excerpts."""
        descriptor = self.descriptor
        preflight = validate_specialist_task(
            task,
            descriptor,
            required_tool_id=self.TOOL_ID,
        )
        if preflight is not None:
            return preflight

        query = task.context.get("search_query", task.question)
        if not isinstance(query, str) or not query.strip():
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="The literature task has no usable search query.",
                error_code="invalid_search_query",
                error_message="context.search_query or task.question must be a non-empty string.",
            )

        arguments: dict[str, Any] = {"query": query.strip()}
        if "top_k" in task.context:
            arguments["top_k"] = task.context["top_k"]

        tool_result = tools.execute(
            ToolRequest(
                call_id=f"{task.task_id}:{self.TOOL_ID}",
                tool_id=self.TOOL_ID,
                arguments=arguments,
            )
        )
        if tool_result.status is ToolStatus.FAILED:
            return AgentResult(
                task_id=task.task_id,
                agent_id=descriptor.agent_id,
                status=AgentStatus.FAILED,
                summary="Reference retrieval failed.",
                evidence=tool_result.evidence,
                tool_ids_used=(self.TOOL_ID,),
                error_code=tool_result.error_code or "literature_search_failed",
                error_message=tool_result.message or "The literature search tool failed.",
                metadata={"tool_result": tool_result.to_dict(), "query": query.strip()},
            )

        findings = tuple(
            Finding(
                finding_id=f"{task.task_id}:{item.evidence_id}",
                statement=item.excerpt,
                finding_type="retrieved_reference_excerpt",
                evidence_ids=(item.evidence_id,),
                data={
                    "title": item.title,
                    "source_uri": item.source_uri,
                    "source_kind": item.source_kind,
                    "record_id": item.record_id,
                    "retrieval": dict(item.metadata).get("retrieval", {}),
                },
            )
            for item in tool_result.evidence
        )
        gaps: tuple[str, ...] = ()
        if not tool_result.evidence:
            gaps = (
                "No usable reference passages were returned within the configured reference scope.",
            )
            status = AgentStatus.INSUFFICIENT_EVIDENCE
            summary = "No usable reference passages were found for this task."
        elif tool_result.status is ToolStatus.PARTIAL:
            status = AgentStatus.PARTIAL
            summary = (
                f"Retrieved {len(tool_result.evidence)} reference passage(s), but some "
                "retrieval results were incomplete or skipped."
            )
            if tool_result.message:
                gaps = (tool_result.message,)
        else:
            status = AgentStatus.SUCCEEDED
            summary = f"Retrieved {len(tool_result.evidence)} reference passage(s)."

        result = AgentResult(
            task_id=task.task_id,
            agent_id=descriptor.agent_id,
            status=status,
            summary=summary,
            findings=findings,
            evidence=tool_result.evidence,
            gaps=gaps,
            tool_ids_used=(self.TOOL_ID,),
            metadata={
                "query": query.strip(),
                "retrieval": dict(tool_result.data),
            },
        )
        result.validate_for(task, descriptor)
        return result
