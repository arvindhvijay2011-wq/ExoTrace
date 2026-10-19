"""A host-planets operation must use the tool's host_name argument contract."""

from typing import Any

from exotrace.agents import AgentStatus, AgentTask, GraphInvestigationAgent
from exotrace.tools.contracts import ToolRequest, ToolResult, ToolStatus


class CapturingExecutor:
    def __init__(self) -> None:
        self.request: ToolRequest | None = None

    def execute(self, request: ToolRequest) -> ToolResult:
        self.request = request
        return ToolResult(
            call_id=request.call_id,
            tool_id=request.tool_id,
            status=ToolStatus.FAILED,
            message="Captured for test only.",
            error_code="test_capture",
        )


def _task(context: dict[str, Any]) -> AgentTask:
    return AgentTask(
        task_id="host-planets-normalization",
        question="Retrieve planets orbiting the Kepler-10 host star.",
        objective="Inspect host-star planet relationships.",
        required_capabilities=("graph.relationships",),
        allowed_tool_ids=("graph.investigate",),
        context=context,
    )


def test_host_planets_normalizes_generic_entity_key_to_host_name() -> None:
    executor = CapturingExecutor()
    agent = GraphInvestigationAgent()
    task = _task({"operation": "host_planets", "planet_name": "Kepler-10", "result_limit": 10})

    result = agent.run(task, tools=executor)  # type: ignore[arg-type]

    assert result.status is AgentStatus.FAILED  # Executor intentionally returns test failure.
    assert executor.request is not None
    assert executor.request.arguments == {
        "operation": "host_planets",
        "host_name": "Kepler-10",
        "result_limit": 10,
    }


def test_host_planets_prefers_explicit_host_name_and_discards_wrong_alias() -> None:
    executor = CapturingExecutor()
    agent = GraphInvestigationAgent()
    task = _task({
        "operation": "host_planets",
        "host_name": "Kepler-10",
        "planet_name": "not-used",
    })

    agent.run(task, tools=executor)  # type: ignore[arg-type]

    assert executor.request is not None
    assert executor.request.arguments == {"operation": "host_planets", "host_name": "Kepler-10"}
