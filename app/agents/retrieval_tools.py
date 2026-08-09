from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents.state import ANNResult, FTSResult, MetadataResult, UnifiedRetrievalResult
from ingestion.embedder import embed_query
from shared.database import get_session


async def ann_search(
    query: str,
    top_k: int = 10,
    similarity_threshold: float = 0.25,
) -> list[UnifiedRetrievalResult]:
    """Approximate Nearest Neighbor search via pgvector cosine similarity.

    Tool for the Retrieval Agent. Embeds the query, then performs
    vector similarity search against all stored chunk embeddings.
    """
    query_embedding = embed_query(query)

    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    d.s3_path,
                    c.content,
                    c.page_number,
                    c.chunk_index,
                    1 - (c.embedding <=> :embedding::vector) AS similarity
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.embedding IS NOT NULL
                  AND 1 - (c.embedding <=> :embedding::vector) > :threshold
                ORDER BY c.embedding <=> :embedding::vector
                LIMIT :limit
            """),
            {
                "embedding": str(query_embedding),
                "threshold": similarity_threshold,
                "limit": top_k,
            },
        )

        return [
            UnifiedRetrievalResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                s3_path=row.s3_path,
                content=row.content,
                score=float(row.similarity),
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                source="ann",
            )
            for row in result.fetchall()
        ]


async def fts_search(
    query: str,
    top_k: int = 10,
) -> list[UnifiedRetrievalResult]:
    """Full-Text Search via PostgreSQL ts_rank.

    Tool for the Retrieval Agent. Uses PostgreSQL's built-in full-text
    search with ts_rank for relevance scoring. Best for exact keyword
    and phrase matching.
    """
    async with get_session() as session:
        result = await session.execute(
            text("""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    d.s3_path,
                    c.content,
                    c.page_number,
                    c.chunk_index,
                    ts_rank_cd(c.search_vector, plainto_tsquery('english', :query)) AS rank
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.search_vector @@ plainto_tsquery('english', :query)
                ORDER BY rank DESC
                LIMIT :limit
            """),
            {"query": query, "limit": top_k},
        )

        return [
            UnifiedRetrievalResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                s3_path=row.s3_path,
                content=row.content,
                score=float(row.rank),
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                source="fts",
            )
            for row in result.fetchall()
        ]


async def metadata_search(
    s3_paths: list[str] | None = None,
    page_range: tuple[int, int] | None = None,
    top_k: int = 10,
) -> list[UnifiedRetrievalResult]:
    """Metadata-filtered search.

    Tool for the Retrieval Agent. Filters chunks by document metadata
    (S3 paths, page numbers) without semantic similarity. Useful for
    scoped retrieval within specific documents.
    """
    conditions = []
    params: dict = {"limit": top_k}

    if s3_paths:
        placeholders = ", ".join(f":path_{i}" for i in range(len(s3_paths)))
        conditions.append(f"d.s3_path IN ({placeholders})")
        for i, path in enumerate(s3_paths):
            params[f"path_{i}"] = path

    if page_range:
        conditions.append("c.page_number >= :page_start")
        conditions.append("c.page_number <= :page_end")
        params["page_start"] = page_range[0]
        params["page_end"] = page_range[1]

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    async with get_session() as session:
        result = await session.execute(
            text(f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    d.s3_path,
                    c.content,
                    c.page_number,
                    c.chunk_index,
                    1.0 AS score
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE {where_clause}
                ORDER BY d.s3_path, c.chunk_index
                LIMIT :limit
            """),
            params,
        )

        return [
            UnifiedRetrievalResult(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                s3_path=row.s3_path,
                content=row.content,
                score=float(row.score),
                page_number=row.page_number,
                chunk_index=row.chunk_index,
                source="metadata",
            )
            for row in result.fetchall()
        ]


async def hybrid_retrieve(
    query: str,
    s3_paths: list[str] | None = None,
    top_k: int = 10,
    ann_weight: float = 0.5,
    fts_weight: float = 0.3,
    metadata_weight: float = 0.2,
) -> list[UnifiedRetrievalResult]:
    """Run all three retrieval tools and merge results via RRF.

    This is the primary tool called by the Retrieval Agent.
    """
    import asyncio

    ann_task = ann_search(query, top_k=top_k)
    fts_task = fts_search(query, top_k=top_k)
    meta_task = metadata_search(s3_paths=s3_paths, top_k=top_k)

    ann_results, fts_results, meta_results = await asyncio.gather(
        ann_task, fts_task, meta_task, return_exceptions=True
    )

    if isinstance(ann_results, Exception):
        ann_results = []
    if isinstance(fts_results, Exception):
        fts_results = []
    if isinstance(meta_results, Exception):
        meta_results = []

    return _rrf_merge(ann_results, fts_results, meta_results, ann_weight, fts_weight, metadata_weight, top_k)


def _rrf_merge(
    ann_results: list[UnifiedRetrievalResult],
    fts_results: list[UnifiedRetrievalResult],
    meta_results: list[UnifiedRetrievalResult],
    ann_weight: float,
    fts_weight: float,
    meta_weight: float,
    top_k: int,
    k: int = 60,
) -> list[UnifiedRetrievalResult]:
    """Reciprocal Rank Fusion merge across three result sets."""
    scores: dict[str, float] = {}
    chunk_map: dict[str, UnifiedRetrievalResult] = {}

    for rank, r in enumerate(ann_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0) + ann_weight / (k + rank + 1)
        chunk_map[r.chunk_id] = r

    for rank, r in enumerate(fts_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0) + fts_weight / (k + rank + 1)
        if r.chunk_id not in chunk_map:
            chunk_map[r.chunk_id] = r

    for rank, r in enumerate(meta_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0) + meta_weight / (k + rank + 1)
        if r.chunk_id not in chunk_map:
            chunk_map[r.chunk_id] = r

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    merged = []
    for cid in sorted_ids[:top_k]:
        result = chunk_map[cid]
        result.score = scores[cid]
        merged.append(result)

    return merged
