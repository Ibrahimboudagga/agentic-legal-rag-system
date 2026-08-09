from __future__ import annotations

from agents.state import AgentState
from agents.retrieval_tools import hybrid_retrieve

from shared.observability.metrics import (
    rag_search_requests_total,
    rag_search_duration_seconds,
    rag_search_results_count,
)

import time


async def retrieval_node(state: AgentState) -> dict:
    """RETRIEVAL: Deterministic multi-tool retrieval.

    NO LLM involved. Calls hybrid_retrieve which runs ANN + FTS + Metadata
    tools in parallel and merges via Reciprocal Rank Fusion.
    """
    query = state["query"]
    s3_paths = state.get("s3_paths", [])
    sub_queries = state.get("sub_queries", [query])
    retrieval_iteration = state.get("retrieval_iteration", 0)
    existing_evidence = state.get("evidence", [])

    search_query = sub_queries[0] if sub_queries else query
    if retrieval_iteration > 0 and len(sub_queries) > 1:
        search_query = sub_queries[min(retrieval_iteration, len(sub_queries) - 1)]

    start = time.monotonic()

    all_results = await hybrid_retrieve(
        query=search_query,
        s3_paths=s3_paths if s3_paths else None,
        top_k=10,
    )

    duration = time.monotonic() - start
    rag_search_requests_total.labels(search_type="hybrid").inc()
    rag_search_duration_seconds.observe(duration)

    existing_ids = {e.get("chunk_id") for e in existing_evidence if e.get("chunk_id")}
    new_results = [r for r in all_results if r.chunk_id not in existing_ids]

    rag_search_results_count.observe(len(new_results))

    retrieval_dicts = [
        {
            "chunk_id": r.chunk_id,
            "document_id": r.document_id,
            "s3_path": r.s3_path,
            "content": r.content,
            "score": r.score,
            "page_number": r.page_number,
            "chunk_index": r.chunk_index,
            "source": r.source,
        }
        for r in new_results
    ]

    return {
        "retrieval_results": retrieval_dicts,
        "tools_used": list({r.source for r in new_results}),
        "retrieval_iteration": retrieval_iteration + 1,
    }
