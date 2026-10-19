"""Registry for specialist agents with explicit responsibilities and capabilities."""

from __future__ import annotations

from collections.abc import Iterable

from exotrace.agents.contracts import AgentDescriptor, SpecialistAgent


class AgentRegistryError(RuntimeError):
    """Raised when agent registration or lookup is invalid."""


class AgentRegistry:
    """Hold specialist implementations and expose their declared capabilities.

    This registry deliberately does not inspect question text or select agents from
    keyword rules. It exposes descriptions so a future orchestrator can plan dynamically.
    """

    def __init__(self, agents: Iterable[SpecialistAgent] = ()) -> None:
        """Create the registry and optionally register initial agents."""
        self._agents: dict[str, SpecialistAgent] = {}
        for agent in agents:
            self.register(agent)

    def register(self, agent: SpecialistAgent) -> None:
        """Register one specialist, rejecting duplicate agent identifiers."""
        descriptor = agent.descriptor
        if not isinstance(descriptor, AgentDescriptor):
            raise TypeError("A registered agent must expose an AgentDescriptor.")
        if descriptor.agent_id in self._agents:
            raise AgentRegistryError(f"Agent is already registered: {descriptor.agent_id!r}.")
        self._agents[descriptor.agent_id] = agent

    def get(self, agent_id: str) -> SpecialistAgent:
        """Return a registered specialist by exact identifier."""
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise AgentRegistryError(f"Unknown agent: {agent_id!r}.") from exc

    def descriptors(self) -> tuple[AgentDescriptor, ...]:
        """Return available specialist descriptions in registration order."""
        return tuple(agent.descriptor for agent in self._agents.values())

    def candidates_for(self, required_capabilities: Iterable[str]) -> tuple[SpecialistAgent, ...]:
        """Return specialists that declare every requested capability.

        Matching is exact and declarative. This method is not an LLM planner and does not
        infer capabilities from a user's wording.
        """
        required = frozenset(required_capabilities)
        if any(not isinstance(item, str) or not item.strip() for item in required):
            raise ValueError("required_capabilities must contain non-empty strings.")
        return tuple(
            agent
            for agent in self._agents.values()
            if required.issubset(set(agent.descriptor.capabilities))
        )
