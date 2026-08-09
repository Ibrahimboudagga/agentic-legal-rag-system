from __future__ import annotations

from langgraph.graph import END, StateGraph

from agents.state import AgentState

# ── Deterministic infrastructure nodes (NO LLM) ──
from agents.retrieval_agent import retrieval_node
from agents.infrastructure_nodes import (
    rerank_node,
    evidence_build_node,
    evidence_validate_node,
)

# ── Agentic reasoning nodes (use LLM via centralized abstraction) ──
from agents.planner import planner_node
from agents.analysis_agent import analysis_node
from agents.comparison_agent import comparison_node
from agents.synthesis_node import synthesis_node


# ── Routing ───────────────────────────────────────────────────────

def route_after_validation(state: AgentState) -> str:
    """Deterministic routing based on evidence validation result."""
    validation = state.get("validation_result", {})
    passed = validation.get("passed", True)
    needs_retrieval = state.get("needs_retrieval", False)
    attempts = state.get("validation_attempts", 0)

    if passed:
        return "analysis"
    if needs_retrieval and attempts < 3:
        return "retrieve_again"
    return "analysis"


def route_after_analysis(state: AgentState) -> str:
    """Deterministic routing based on comparison flag."""
    if state.get("comparison_needed", False):
        return "comparison"
    return "synthesize"


# ── Graph Builder ─────────────────────────────────────────────────

def build_agent_graph() -> StateGraph:
    """Build the Agentic RAG LangGraph workflow.

    Category A — Deterministic Infrastructure (NO LLM):
        retrieval → rerank → evidence_build → evidence_validate

    Category B — Agentic Reasoning (LLM via centralized abstraction):
        planner → [decides strategy]
        analysis → [legal analysis]
        comparison → [cross-contract]
        synthesis → [final report]

    Category C — LLM Inference:
        All LLM calls go through shared.llm_client.get_llm_client()
    """
    graph = StateGraph(AgentState)

    # ── Reasoning nodes ──
    graph.add_node("planner", planner_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("comparison", comparison_node)
    graph.add_node("synthesize", synthesis_node)

    # ── Infrastructure nodes ──
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("evidence_build", evidence_build_node)
    graph.add_node("evidence_validate", evidence_validate_node)

    # ── Wiring ──
    graph.set_entry_point("planner")
    graph.add_edge("planner", "retrieval")
    graph.add_edge("retrieval", "rerank")
    graph.add_edge("rerank", "evidence_build")
    graph.add_edge("evidence_build", "evidence_validate")

    graph.add_conditional_edges(
        "evidence_validate",
        route_after_validation,
        {
            "analysis": "analysis",
            "retrieve_again": "retrieval",
        },
    )

    graph.add_conditional_edges(
        "analysis",
        route_after_analysis,
        {
            "comparison": "comparison",
            "synthesize": "synthesize",
        },
    )

    graph.add_edge("comparison", "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()


_agent_graph = None
_evidence_store = None


def get_agent_graph():
    """Get or build the compiled agent graph (singleton)."""
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph


def reset_evidence_store():
    """Reset the evidence store singleton between runs."""
    global _evidence_store
    _evidence_store = None
