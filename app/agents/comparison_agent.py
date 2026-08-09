from __future__ import annotations

from agents.state import AgentState
from shared.llm_client import get_llm_client


async def comparison_node(state: AgentState) -> dict:
    """COMPARISON: Agentic reasoning — cross-contract risk analysis.

    Uses LLM via centralized abstraction.
    Only runs when comparison_needed=True.
    """
    llm = get_llm_client()
    query = state["query"]
    analysis = state.get("analysis", {})
    evidence = state.get("evidence", [])
    s3_paths = state.get("s3_paths", [])

    if len(s3_paths) < 2:
        return {
            "comparison": {
                "cross_contract_risks": [],
                "contract_interactions": [],
                "overall_risk_level": "N/A",
                "patterns": [],
            }
        }

    evidence_parts = []
    for item in evidence:
        evidence_parts.append(
            f"[Citation {item.get('citation_id', '?')}: {item.get('s3_path', '')} | "
            f"Page {item.get('page_number', 'N/A')}]\n{item.get('content', '')}"
        )

    evidence_context = "\n\n---\n\n".join(evidence_parts)

    import json
    comparison = await llm.complete_json(
        prompt=f"""Perform cross-contract risk analysis.

USER QUERY:
{query}

CONTRACTS IN SCOPE:
{json.dumps(s3_paths, indent=2)}

INDIVIDUAL ANALYSIS:
{json.dumps(analysis, indent=2)}

EVIDENCE:
{evidence_context}

Identify cross-contract risks, interactions, patterns, and missing protections.

Return a JSON object:
{{
  "cross_contract_risks": [
    {{
      "risk": "description",
      "affected_contracts": ["path1.pdf", "path2.pdf"],
      "severity": "Critical / High / Medium / Low",
      "explanation": "why this matters",
      "citation_ids": [1, 2]
    }}
  ],
  "contract_interactions": [
    {{
      "interaction": "how contracts interact",
      "contracts_involved": ["path1.pdf", "path2.pdf"],
      "impact": "business/legal impact"
    }}
  ],
  "overall_risk_level": "Critical / High / Medium / Low",
  "patterns": ["pattern 1", "pattern 2"],
  "missing_protections": ["protection 1"],
  "recommendations": ["recommendation 1"]
}}
""",
        system="You are a cross-contract legal analyst. Respond with valid JSON only.",
        max_tokens=6000,
    )

    return {"comparison": comparison}
