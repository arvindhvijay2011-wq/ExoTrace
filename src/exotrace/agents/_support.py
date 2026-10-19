"""Shared validation helpers for bounded specialist agents."""

from __future__ import annotations

from exotrace.agents.contracts import AgentDescriptor, AgentResult, AgentStatus, AgentTask


def validate_specialist_task(
    task: AgentTask,
    descriptor: AgentDescriptor,
    *,
    required_tool_id: str,
) -> AgentResult | None:
    """Return a failed result when a task exceeds the specialist's declared contract.

    The helper checks declared capabilities and task permissions only. It does not inspect
    the question text or infer a task type from keywords.
    """
    missing_capabilities = sorted(
        set(task.required_capabilities) - set(descriptor.capabilities)
    )
    if missing_capabilities:
        return AgentResult(
            task_id=task.task_id,
            agent_id=descriptor.agent_id,
            status=AgentStatus.FAILED,
            summary="The task requests capabilities outside this specialist's responsibility.",
            gaps=("Unsupported required capabilities: " + ", ".join(missing_capabilities),),
            error_code="unsupported_capability",
            error_message=(
                "The specialist cannot perform required capabilities: "
                + ", ".join(missing_capabilities)
            ),
        )

    if required_tool_id not in descriptor.allowed_tool_ids:
        return AgentResult(
            task_id=task.task_id,
            agent_id=descriptor.agent_id,
            status=AgentStatus.FAILED,
            summary="The specialist implementation is missing its required tool permission.",
            error_code="agent_tool_not_configured",
            error_message=f"Agent descriptor does not grant {required_tool_id!r}.",
        )

    if required_tool_id not in task.allowed_tool_ids:
        return AgentResult(
            task_id=task.task_id,
            agent_id=descriptor.agent_id,
            status=AgentStatus.FAILED,
            summary="The assigned task does not grant the specialist its required tool.",
            gaps=(f"Task must explicitly allow tool {required_tool_id!r}.",),
            error_code="task_tool_not_granted",
            error_message=f"Task allowlist does not include {required_tool_id!r}.",
        )

    return None
