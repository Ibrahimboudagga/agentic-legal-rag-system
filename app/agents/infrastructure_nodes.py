from __future__ import annotations

from agents.state import AgentState
from agents.reranker import rerank_chunks
from agents.state import UnifiedRetrievalResult

from shared.observability.metrics import (
    agent_analysis_requests_total,
    agent_analysis_duration_seconds,
    evidence_validation_failures_total,
)

import time


async def rerank_node(state: AgentState) -> dict:
    """RERANK: Deterministic cross-encoder reranking.

    NO LLM involved. Uses a local cross-encoder model
    (cross-encoder/ms-marco-MiniLM-L-6-v2) to score relevance.
    """
    chunks_raw = state.get("retrieval_results", [])
    if not chunks_raw:
        return {"reranked_chunks": []}

    chunks = [UnifiedRetrievalResult(**c) for c in chunks_raw]
    reranked = rerank_chunks(state["query"], chunks, top_k=state.get("top_k", 8))

    return {
        "reranked_chunks": [
            {
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
                "s3_path": r.s3_path,
                "content": r.content,
                "original_score": r.original_score,
                "rerank_score": r.rerank_score,
                "source": r.source,
                "page_number": r.page_number,
                "page_start": r.page_start,
                "page_end": r.page_end,
                "section": r.section,
                "clause": r.clause,
                "chunk_index": r.chunk_index,
            }
            for r in reranked
        ]
    }


async def evidence_build_node(state: AgentState) -> dict:
    """EVIDENCE BUILD: Deterministic evidence accumulation.

    NO LLM involved. Accumulates reranked chunks into the evidence store
    with deduplication and citation tracking.
    """
    from agents.evidence_store import EvidenceStore

    store = state.get("_evidence_store")
    if store is None:
        store = EvidenceStore()

    chunks_raw = state.get("reranked_chunks", [])
    if not chunks_raw:
        chunks_raw = state.get("retrieval_results", [])

    if chunks_raw:
        from agents.state import RerankedChunk
        valid_chunks = []
        for c in chunks_raw:
            if isinstance(c, dict) and "rerank_score" in c:
                valid_chunks.append(RerankedChunk(**c))
        if valid_chunks:
            store.add_from_reranked(valid_chunks)
        else:
            store.add_raw(chunks_raw)

    return {
        "evidence": [
            {
                "chunk_id": item.chunk_id,
                "document_id": item.document_id,
                "s3_path": item.s3_path,
                "content": item.content,
                "page_number": item.page_number,
                "page_start": item.page_start,
                "page_end": item.page_end,
                "section": item.section,
                "clause": item.clause,
                "relevance_score": item.relevance_score,
                "citation_id": item.citation_id,
                "source_tool": item.source_tool,
                "validation_status": item.validation_status,
            }
            for item in store.get_all()
        ],
        "evidence_citations": store.get_citations(),
        "evidence_count": store.count(),
        "_evidence_store": store,
    }


async def evidence_validate_node(state: AgentState) -> dict:
    """EVIDENCE VALIDATE: Deterministic validation.

    NO LLM involved. Uses heuristic checks for sufficiency,
    coverage, source diversity, and consistency.
    """
    from agents.evidence_validator import validate_evidence

    store = state.get("_evidence_store")
    if store is None:
        from agents.evidence_store import EvidenceStore
        store = EvidenceStore()

    validation = validate_evidence(
        query=state["query"],
        evidence_store=store,
        analysis_focus=state.get("analysis_focus"),
    )
    for issue in validation.issues:
        evidence_validation_failures_total.labels(issue_type=issue.issue_type).inc()

    return {
        "validation_result": {
            "passed": validation.passed,
            "coverage_score": validation.coverage_score,
            "consistency_score": validation.consistency_score,
            "supported": validation.supported,
            "confidence": validation.confidence,
            "reason": validation.reason,
            "issues": [
                {
                    "issue_type": issue.issue_type,
                    "description": issue.description,
                    "chunk_id": issue.chunk_id,
                    "severity": issue.severity,
                }
                for issue in validation.issues
            ],
            "suggestions": validation.suggestions,
            "missing_information": validation.missing_information,
            "needs_retrieval": validation.needs_retrieval,
        },
        "needs_retrieval": validation.needs_retrieval,
        "missing_information": validation.missing_information or validation.suggestions,
        "validation_attempts": state.get("validation_attempts", 0) + 1,
        "_evidence_store": store,
    }
