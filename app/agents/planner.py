from __future__ import annotations

from agents.state import AgentState
from shared.llm_client import get_llm_client


async def planner_node(state: AgentState) -> dict:
    """PLANNER: Agentic reasoning — decompose query into sub-tasks.

    Uses LLM via centralized abstraction.
    """
    llm = get_llm_client()
    query = state["query"]
    s3_paths = state.get("s3_paths", [])

    doc_info = f"Documents in scope: {len(s3_paths)} contract(s)" if s3_paths else "No specific documents scoped"

    plan = await llm.complete_json(
        prompt=f"""Decompose the following legal query into a structured retrieval and analysis plan.

USER QUERY:
{query}

{doc_info}
DOCUMENT PATHS: {chr(10).join(s3_paths) if s3_paths else "N/A"}

Return a JSON object:
{{
  "sub_queries": ["specific sub-query 1", "sub-query 2", ...],
  "comparison_needed": true/false,
  "analysis_focus": ["focus area 1", "focus area 2", ...],
  "retrieval_strategy": "broad / focused / exhaustive"
}}

comparison_needed should be true if multiple contracts are in scope or the query implies comparison.
analysis_focus should list the specific legal aspects to investigate.
sub_queries should be 3-5 specific, targeted questions for retrieval.
""",
        system="You are a legal analysis planner. Respond with valid JSON only.",
    )

    return {
        "plan": plan,
        "sub_queries": plan.get("sub_queries", [query]),
        "comparison_needed": plan.get("comparison_needed", len(s3_paths) > 1),
        "analysis_focus": plan.get("analysis_focus", []),
    }
