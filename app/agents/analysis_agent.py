from __future__ import annotations

from agents.state import AgentState
from shared.llm_client import get_llm_client


async def analysis_node(state: AgentState) -> dict:
    """ANALYSIS: Agentic reasoning — legal analysis on validated evidence.

    Uses LLM via centralized abstraction.
    """
    llm = get_llm_client()
    query = state["query"]
    evidence = state.get("evidence", [])
    analysis_focus = state.get("analysis_focus", [])

    if not evidence:
        return {
            "analysis": {
                "findings": [],
                "risk_level": "unknown",
                "summary": "No evidence available for analysis.",
                "confidence": 0.0,
                "citations_used": [],
            }
        }

    evidence_parts = []
    for item in evidence:
        evidence_parts.append(
            f"[Citation {item.get('citation_id', '?')}: {item.get('s3_path', '')} | "
            f"Page {item.get('page_number', 'N/A')} | "
            f"Score: {item.get('relevance_score', 0):.3f}]\n{item.get('content', '')}"
        )

    evidence_context = "\n\n---\n\n".join(evidence_parts)
    focus_str = ", ".join(analysis_focus) if analysis_focus else "all relevant legal aspects"

    analysis = await llm.complete_json(
        prompt=f"""Analyze the following evidence in relation to the user's query.

USER QUERY:
{query}

ANALYSIS FOCUS: {focus_str}

VALIDATED EVIDENCE ({len(evidence)} items):
{evidence_context}

Perform a thorough legal analysis. Every finding MUST reference at least one citation_id.

Return a JSON object:
{{
  "findings": [
    {{
      "topic": "specific legal topic",
      "analysis": "detailed legal analysis",
      "risk_level": "High / Medium / Low",
      "legal_basis": "legal principle or clause reference",
      "citation_ids": [1, 2],
      "implications": "what this means for the parties"
    }}
  ],
  "overall_risk_level": "High / Medium / Low",
  "summary": "3-5 sentence executive summary",
  "confidence": 0.0-1.0,
  "citations_used": [1, 2, 3]
}}
""",
        system="You are a senior legal analyst. Respond with valid JSON only.",
        max_tokens=8000,
    )

    return {"analysis": analysis}
