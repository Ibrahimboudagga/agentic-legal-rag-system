from __future__ import annotations

from agents.state import AgentState
from shared.llm_client import get_llm_client


async def synthesis_node(state: AgentState) -> dict:
    """SYNTHESIS: Agentic reasoning — final evidence-grounded report.

    Uses LLM via centralized abstraction.
    """
    llm = get_llm_client()
    query = state["query"]
    analysis = state.get("analysis", {})
    comparison = state.get("comparison", {})
    evidence = state.get("evidence", [])
    validation = state.get("validation_result", {})

    citations = [
        {
            "citation_id": item.get("citation_id", 0),
            "s3_path": item.get("s3_path", ""),
            "page_number": item.get("page_number"),
            "excerpt": item.get("content", "")[:200],
        }
        for item in evidence
    ]

    import json
    synthesis = await llm.complete_json(
        prompt=f"""Produce the final evidence-grounded legal report.

USER QUERY:
{query}

LEGAL ANALYSIS:
{json.dumps(analysis, indent=2)}

CROSS-CONTRACT COMPARISON:
{json.dumps(comparison, indent=2)}

EVIDENCE CITATIONS ({len(citations)} items):
{json.dumps(citations[:20], indent=2)}

VALIDATION:
Coverage: {validation.get('coverage_score', 'N/A')}
Consistency: {validation.get('consistency_score', 'N/A')}

Every factual claim MUST reference a citation_id. Recommendations MUST be actionable.

Return a JSON object:
{{
  "query": "the original query",
  "executive_summary": "3-5 sentence summary for senior leadership",
  "detailed_findings": [
    {{
      "topic": "string",
      "analysis": "detailed legal analysis",
      "risk_level": "High / Medium / Low",
      "legal_basis": "string",
      "evidence": [
        {{"citation_id": 1, "s3_path": "string", "page_number": null, "excerpt": "exact text"}}
      ],
      "implications": "string"
    }}
  ],
  "cross_contract_analysis": {{
    "present": true/false,
    "risks": [...],
    "patterns": [...]
  }},
  "overall_risk_level": "Critical / High / Medium / Low",
  "risk_justification": "why this rating",
  "recommendations": [
    {{
      "priority": "High / Medium / Low",
      "action": "specific action",
      "rationale": "why this action",
      "citations": [1, 2]
    }}
  ],
  "evidence_quality": {{
    "total_citations": {len(citations)},
    "coverage_score": {validation.get('coverage_score', 0)},
    "validation_passed": {str(validation.get('passed', False)).lower()}
  }},
  "citations": {json.dumps(citations[:20])}
}}
""",
        system="You are a senior legal partner. Respond with valid JSON only.",
        max_tokens=10000,
    )

    return {"synthesis": synthesis}
