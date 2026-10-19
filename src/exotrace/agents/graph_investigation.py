"""Specialist agent for read-only graph relationships and their source provenance."""

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
from exotrace.contracts import Finding
from exotrace.tools.contracts import ToolExecutor, ToolRequest, ToolStatus
from exotrace.tools.graph_investigation import GraphInvestigationTool


class GraphInvestigationAgent:
    """Investigate explicitly selected graph relationships without interpreting science.

    This agent requires structured operation arguments from a caller. It never extracts entity
    names or chooses graph operations from natural-language question keywords. Its only tool is
    ``graph.investigate``; it does not read raw catalogue measurement fields or literature.
    """

    AGENT_ID = "graph_investigation"
    TOOL_ID = GraphInvestigationTool.TOOL_ID

    @property
    def descriptor(self) -> AgentDescriptor:
        """Declare the graph-only responsibility and single permitted tool."""
        return AgentDescriptor(
            agent_id=self.AGENT_ID,
            name="Graph Investigation Agent",
            responsibility=(
                "Retrieve read-only graph relationships among planets, host stars, discovery "
                "methods, discovery facilities, publication references, and source catalogue "
                "records. Preserve edge-level source-record and snapshot provenance. Do not "
                "interpret scientific significance, calculate measurements, or search prose."
            ),
            capabilities=("graph.read", "graph.relationships", "source.provenance"),
            allowed_tool_ids=(self.TOOL_ID,),
            task_context_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": list(GraphInvestigationTool.SUPPORTED_OPERATIONS),
                    },
                    "planet_name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Planet identifier for planet_context or planet_records; not host_planets.",
                    },
                    "host_name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Host-star identifier required by host_planets.",
                    },
                    "result_limit": {"type": "integer", "minimum": 1},
                },
                "required": ["operation"],
                "additionalProperties": False,
            },
        )

    def run(self, task: AgentTask, *, tools: ToolExecutor) -> AgentResult:
        """Execute one structured graph investigation and return provenance-backed findings."""
        descriptor = self.descriptor
        preflight = validate_specialist_task(
            task,
            descriptor,
            required_tool_id=self.TOOL_ID,
        )
        if preflight is not None:
            return preflight

        # Forward only the declared operation fields. This is a transport boundary, not a
        # question router; selection of operation/entity belongs to the future planner.
        allowed_context_keys = ("operation", "planet_name", "host_name", "result_limit")
        arguments: dict[str, Any] = {
            key: task.context[key]
            for key in allowed_context_keys
            if key in task.context
        }
        # Some planner outputs use the generic entity field for host_planets even though
        # the registered tool schema names that argument host_name. Normalize the argument
        # key based only on the explicit operation contract, never on question text.
        if arguments.get("operation") == "host_planets":
            if not arguments.get("host_name") and isinstance(arguments.get("planet_name"), str):
                arguments["host_name"] = arguments["planet_name"]
            arguments.pop("planet_name", None)

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
                summary="The graph investigation failed.",
                evidence=tool_result.evidence,
                tool_ids_used=(self.TOOL_ID,),
                error_code=tool_result.error_code or "graph_investigation_failed",
                error_message=tool_result.message or "The graph tool failed.",
                metadata={"tool_result": tool_result.to_dict()},
            )

        graph_facts = tool_result.data.get("graph_facts", [])
        findings: list[Finding] = []
        if isinstance(graph_facts, list):
            for fact in graph_facts:
                if not isinstance(fact, dict):
                    continue
                evidence_id = fact.get("evidence_id")
                statement = fact.get("statement")
                finding_type = fact.get("finding_type")
                data = fact.get("data")
                if (
                    not isinstance(evidence_id, str)
                    or not evidence_id.strip()
                    or not isinstance(statement, str)
                    or not statement.strip()
                    or not isinstance(finding_type, str)
                    or not finding_type.strip()
                    or not isinstance(data, dict)
                ):
                    continue
                findings.append(
                    Finding(
                        finding_id=f"{task.task_id}:{evidence_id}",
                        statement=statement,
                        finding_type=finding_type,
                        evidence_ids=(evidence_id,),
                        data=data,
                    )
                )

        if not tool_result.evidence or not findings:
            status = AgentStatus.INSUFFICIENT_EVIDENCE
            summary = "No source-backed graph relationships were available for this task."
            gaps = (tool_result.message or "No source-backed graph facts were returned.",)
        elif tool_result.status is ToolStatus.PARTIAL:
            status = AgentStatus.PARTIAL
            summary = (
                f"Retrieved {len(findings)} source-backed graph relationship(s), "
                "with limitations."
            )
            gaps = (
                (tool_result.message,)
                if tool_result.message
                else ("The graph result is partial.",)
            )
        else:
            status = AgentStatus.SUCCEEDED
            summary = f"Retrieved {len(findings)} source-backed graph relationship(s)."
            gaps = ()

        result = AgentResult(
            task_id=task.task_id,
            agent_id=descriptor.agent_id,
            status=status,
            summary=summary,
            findings=tuple(findings),
            evidence=tool_result.evidence,
            gaps=gaps,
            tool_ids_used=(self.TOOL_ID,),
            metadata={"investigation": tool_result.data},
        )
        result.validate_for(task, descriptor)
        return result
