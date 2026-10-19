"""Tool registry and per-task permission-restricted tool execution."""

from __future__ import annotations

from typing import Iterable

from exotrace.agents.contracts import AgentDescriptor, AgentTask
from exotrace.tools.contracts import ExoTraceTool, ToolDescriptor, ToolRequest, ToolResult


class ToolRegistryError(RuntimeError):
    """Raised when a tool registry is misconfigured or a tool violates its contract."""


class ToolAccessDenied(PermissionError):
    """Raised when an agent requests a tool not granted by both permission lists."""


class ToolRegistry:
    """Register and inspect tools without implementing task-specific routing."""

    def __init__(self, tools: Iterable[ExoTraceTool] = ()) -> None:
        """Create a registry and optionally add initial tool implementations."""
        self._tools: dict[str, ExoTraceTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ExoTraceTool) -> None:
        """Register one tool, rejecting duplicate identifiers."""
        descriptor = tool.descriptor
        if not isinstance(descriptor, ToolDescriptor):
            raise TypeError("A registered tool must expose a ToolDescriptor.")
        if descriptor.tool_id in self._tools:
            raise ToolRegistryError(f"Tool is already registered: {descriptor.tool_id!r}.")
        self._tools[descriptor.tool_id] = tool

    def get(self, tool_id: str) -> ExoTraceTool:
        """Return a registered tool by exact identifier."""
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise ToolRegistryError(f"Unknown tool: {tool_id!r}.") from exc

    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        """Return registered tool descriptions in registration order."""
        return tuple(tool.descriptor for tool in self._tools.values())

    def executor_for(self, agent: AgentDescriptor, task: AgentTask) -> RestrictedToolExecutor:
        """Create an executor restricted by both the agent and task allowlists."""
        permitted = set(agent.allowed_tool_ids) & set(task.allowed_tool_ids)
        unknown = sorted(permitted - self._tools.keys())
        if unknown:
            raise ToolRegistryError(f"Permission lists name unregistered tools: {unknown}.")
        return RestrictedToolExecutor(self, permitted_tool_ids=permitted)


class RestrictedToolExecutor:
    """Enforce least-privilege tool access for a single specialist task."""

    def __init__(self, registry: ToolRegistry, *, permitted_tool_ids: Iterable[str]) -> None:
        """Create a restricted tool facade from an already-resolved permission set."""
        self._registry = registry
        self._permitted_tool_ids = frozenset(permitted_tool_ids)

    @property
    def permitted_tool_ids(self) -> frozenset[str]:
        """Return the immutable set of tools available to this task."""
        return self._permitted_tool_ids

    def execute(self, request: ToolRequest) -> ToolResult:
        """Execute a permitted tool and validate response identity before returning it."""
        if request.tool_id not in self._permitted_tool_ids:
            raise ToolAccessDenied(
                f"Tool {request.tool_id!r} is not permitted for this agent task."
            )
        tool = self._registry.get(request.tool_id)
        result = tool.execute(request)
        if not isinstance(result, ToolResult):
            raise ToolRegistryError(
                f"Tool {request.tool_id!r} returned {type(result).__name__}; "
                "expected ToolResult."
            )
        if result.call_id != request.call_id or result.tool_id != request.tool_id:
            raise ToolRegistryError(
                "Tool result identity does not match the corresponding request."
            )
        return result
