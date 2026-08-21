from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    capabilities: tuple[str, ...]


_AGENTS: tuple[AgentDefinition, ...] = (
    AgentDefinition(
        name="termination_analyzer",
        description="Analyzes termination rights, notice periods, cure periods, and unilateral termination risk.",
        capabilities=("termination", "notice_period", "early_termination", "termination_for_convenience"),
    ),
    AgentDefinition(
        name="liability_analyzer",
        description="Analyzes liability caps, exclusions, consequential damages, and uncapped exposure.",
        capabilities=("liability", "liability_cap", "damages", "risk_allocation"),
    ),
    AgentDefinition(
        name="confidentiality_analyzer",
        description="Analyzes confidentiality duties, permitted disclosures, duration, and survival.",
        capabilities=("confidentiality", "nda", "disclosure", "survival"),
    ),
    AgentDefinition(
        name="indemnification_analyzer",
        description="Analyzes indemnities, defense obligations, third-party claims, and exclusions.",
        capabilities=("indemnification", "defense", "third_party_claims"),
    ),
    AgentDefinition(
        name="comparison_analyzer",
        description="Compares risk posture and clause differences across multiple contracts.",
        capabilities=("comparison", "cross_contract_comparison", "conflict_detection"),
    ),
)


def list_agent_definitions() -> list[AgentDefinition]:
    return list(_AGENTS)


def capability_prompt_fragment() -> str:
    lines = []
    for agent in _AGENTS:
        lines.append(
            f"- {agent.name}: {agent.description} Capabilities: {', '.join(agent.capabilities)}"
        )
    return "\n".join(lines)


def known_capabilities() -> set[str]:
    capabilities: set[str] = set()
    for agent in _AGENTS:
        capabilities.update(agent.capabilities)
    return capabilities


def select_capabilities(requested: list[str]) -> list[str]:
    known = known_capabilities()
    return [capability for capability in requested if capability in known]
