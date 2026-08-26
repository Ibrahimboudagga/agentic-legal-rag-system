from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ingestion.embedder import embed_query
from retrieval.vector_store import SearchResult, search_keyword, search_semantic


@dataclass
class HybridSearchConfig:
    semantic_top_k: int = 10
    keyword_top_k: int = 10
    final_top_k: int = 5
    semantic_weight: float = 0.7
    keyword_weight: float = 0.3
    similarity_threshold: float = 0.25


_DEFAULT_CONFIG = HybridSearchConfig(
    semantic_top_k=int(os.getenv("HYBRID_SEMANTIC_TOP_K", "10")),
    keyword_top_k=int(os.getenv("HYBRID_KEYWORD_TOP_K", "10")),
    final_top_k=int(os.getenv("HYBRID_FINAL_TOP_K", "5")),
    semantic_weight=float(os.getenv("HYBRID_SEMANTIC_WEIGHT", "0.7")),
    keyword_weight=float(os.getenv("HYBRID_KEYWORD_WEIGHT", "0.3")),
    similarity_threshold=float(os.getenv("HYBRID_SIMILARITY_THRESHOLD", "0.25")),
)


async def hybrid_search(
    session: AsyncSession,
    query: str,
    config: HybridSearchConfig | None = None,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion hybrid search combining semantic + keyword results.

    1. Run semantic search (pgvector cosine similarity)
    2. Run keyword search (PostgreSQL full-text search with ts_rank)
    3. Merge via Reciprocal Rank Fusion (RRF)
    4. Return top_k results
    """
    cfg = config or _DEFAULT_CONFIG

    query_embedding = embed_query(query)

    semantic_results, keyword_results = await _run_parallel_searches(
        session, query, query_embedding, cfg
    )

    merged = _reciprocal_rank_fusion(
        semantic_results, keyword_results,
        semantic_weight=cfg.semantic_weight,
        keyword_weight=cfg.keyword_weight,
    )

    return merged[: cfg.final_top_k]


async def _run_parallel_searches(
    session: AsyncSession,
    query: str,
    query_embedding: list[float],
    config: HybridSearchConfig,
) -> tuple[list[SearchResult], list[SearchResult]]:
    """Run semantic and keyword searches concurrently."""
    import asyncio

    semantic_task = search_semantic(
        session, query_embedding,
        top_k=config.semantic_top_k,
        similarity_threshold=config.similarity_threshold,
    )
    keyword_task = search_keyword(session, query, top_k=config.keyword_top_k)

    semantic_results, keyword_results = await asyncio.gather(
        semantic_task, keyword_task, return_exceptions=True
    )

    if isinstance(semantic_results, Exception):
        semantic_results = []
    if isinstance(keyword_results, Exception):
        keyword_results = []

    return semantic_results, keyword_results


def _reciprocal_rank_fusion(
    semantic_results: list[SearchResult],
    keyword_results: list[SearchResult],
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
    k: int = 60,
) -> list[SearchResult]:
    """Merge two ranked lists using Reciprocal Rank Fusion.

    RRF score = weight / (k + rank) for each result.
    If a chunk appears in both lists, scores are summed.
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, SearchResult] = {}

    for rank, result in enumerate(semantic_results):
        key = result.chunk_id
        scores[key] = scores.get(key, 0) + semantic_weight / (k + rank + 1)
        chunk_map[key] = result

    for rank, result in enumerate(keyword_results):
        key = result.chunk_id
        scores[key] = scores.get(key, 0) + keyword_weight / (k + rank + 1)
        if key not in chunk_map:
            chunk_map[key] = result

    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)

    merged = []
    for key in sorted_keys:
        result = chunk_map[key]
        result.score = scores[key]
        merged.append(result)

    return merged
