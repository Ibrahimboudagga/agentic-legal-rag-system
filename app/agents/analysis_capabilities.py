from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisCapability:
    name: str
    instruction: str


_CAPABILITIES: dict[str, AnalysisCapability] = {
    "termination": AnalysisCapability(
        name="termination",
        instruction="Evaluate termination rights, notice requirements, cure periods, termination for convenience, and post-termination obligations.",
    ),
    "notice_period": AnalysisCapability(
        name="notice_period",
        instruction="Identify exact notice periods, triggering events, delivery requirements, and timing ambiguity.",
    ),
    "early_termination": AnalysisCapability(
        name="early_termination",
        instruction="Assess unilateral or early termination rights and whether they create commercial leverage or operational risk.",
    ),
    "termination_for_convenience": AnalysisCapability(
        name="termination_for_convenience",
        instruction="Determine whether either party can terminate without cause and what fees, wind-down duties, or refunds apply.",
    ),
    "liability": AnalysisCapability(
        name="liability",
        instruction="Analyze liability allocation, liability caps, exclusions, exceptions, and uncapped exposure.",
    ),
    "liability_cap": AnalysisCapability(
        name="liability_cap",
        instruction="Extract the liability cap formula and identify carve-outs, super-caps, and ambiguous cap language.",
    ),
    "damages": AnalysisCapability(
        name="damages",
        instruction="Check exclusions of consequential, indirect, special, punitive, lost profit, and data loss damages.",
    ),
    "risk_allocation": AnalysisCapability(
        name="risk_allocation",
        instruction="Explain how risk is allocated between parties and flag one-sided allocation or missing remedies.",
    ),
    "confidentiality": AnalysisCapability(
        name="confidentiality",
        instruction="Review confidentiality scope, exclusions, permitted disclosures, protection standards, return/destruction duties, and survival.",
    ),
    "nda": AnalysisCapability(
        name="nda",
        instruction="Assess NDA-style obligations, recipient duties, disclosure controls, and residual knowledge or compelled disclosure terms.",
    ),
    "disclosure": AnalysisCapability(
        name="disclosure",
        instruction="Identify who may disclose confidential information, under what approvals, and with what downstream obligations.",
    ),
    "survival": AnalysisCapability(
        name="survival",
        instruction="Check whether obligations survive termination and whether the survival period is definite, indefinite, or missing.",
    ),
    "indemnification": AnalysisCapability(
        name="indemnification",
        instruction="Analyze indemnity triggers, covered losses, procedure, control of defense, settlement rights, exclusions, and caps.",
    ),
    "defense": AnalysisCapability(
        name="defense",
        instruction="Evaluate defense obligations, notice requirements, cooperation duties, counsel control, and settlement consent.",
    ),
    "third_party_claims": AnalysisCapability(
        name="third_party_claims",
        instruction="Separate third-party claim coverage from direct party claims and flag drafting that blurs those categories.",
    ),
    "comparison": AnalysisCapability(
        name="comparison",
        instruction="Compare clauses across scoped contracts and identify materially different rights, obligations, risk levels, and conflicts.",
    ),
    "cross_contract_comparison": AnalysisCapability(
        name="cross_contract_comparison",
        instruction="Normalize clause positions across contracts so differences are visible and comparable.",
    ),
    "conflict_detection": AnalysisCapability(
        name="conflict_detection",
        instruction="Look for inconsistent obligations, incompatible timelines, conflicting remedies, or contradictory party duties.",
    ),
}


def selected_capabilities(requested: list[str]) -> list[AnalysisCapability]:
    return [_CAPABILITIES[name] for name in requested if name in _CAPABILITIES]


def capability_instruction_block(requested: list[str]) -> str:
    selected = selected_capabilities(requested)
    if not selected:
        return "- General contract review: analyze the evidence against the query and identify supported risks, obligations, gaps, and recommendations."
    return "\n".join(f"- {capability.name}: {capability.instruction}" for capability in selected)
