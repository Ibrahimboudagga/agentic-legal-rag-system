from __future__ import annotations

import asyncio

from sqlalchemy import text

from agents.state import UnifiedRetrievalResult
from ingestion.embedder import get_embedding_provider
from shared.database import get_session


async def vector_search(
    query: str,
    top_k: int,
    similarity_threshold: float,
    s3_paths: list[str] | None = None,
) -> list[UnifiedRetrievalResult]:
    embedding_provider = get_embedding_provider()
    query_embedding = await embedding_provider.embed_query(query)
    path_filter, params = _path_filter_sql(s3_paths)
    params.update({
        "embedding": str(query_embedding),
        "threshold": similarity_threshold,
        "limit": top_k,
    })

    async with get_session() as session:
        result = await session.execute(
            text(f"""
                SELECT c.id AS chunk_id, c.document_id, d.s3_path, c.content,
                       c.page_number, c.page_start, c.page_end, c.section, c.clause,
                       c.chunk_index,
                       1 - (c.embedding <=> :embedding::vector) AS similarity
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.embedding IS NOT NULL
                  AND 1 - (c.embedding <=> :embedding::vector) > :threshold
                  {path_filter}
                ORDER BY c.embedding <=> :embedding::vector
                LIMIT :limit
            """),
            params,
        )
        return [_row_to_result(row, "ann", float(row.similarity)) for row in result.fetchall()]


async def keyword_search(
    query: str,
    top_k: int,
    s3_paths: list[str] | None = None,
) -> list[UnifiedRetrievalResult]:
    path_filter, params = _path_filter_sql(s3_paths)
    params.update({"query": query, "limit": top_k})

    async with get_session() as session:
        result = await session.execute(
            text(f"""
                SELECT c.id AS chunk_id, c.document_id, d.s3_path, c.content,
                       c.page_number, c.page_start, c.page_end, c.section, c.clause,
                       c.chunk_index,
                       ts_rank_cd(c.search_vector, plainto_tsquery('english', :query)) AS rank
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.search_vector @@ plainto_tsquery('english', :query)
                  {path_filter}
                ORDER BY rank DESC
                LIMIT :limit
            """),
            params,
        )
        return [_row_to_result(row, "fts", float(row.rank)) for row in result.fetchall()]


async def metadata_search(
    s3_paths: list[str] | None,
    top_k: int,
    section: str | None = None,
    clause: str | None = None,
    language: str | None = None,
    document_type: str | None = None,
) -> list[UnifiedRetrievalResult]:
    conditions = []
    params: dict = {"limit": top_k}

    if s3_paths:
        placeholders = ", ".join(f":path_{i}" for i in range(len(s3_paths)))
        conditions.append(f"d.s3_path IN ({placeholders})")
        for i, path in enumerate(s3_paths):
            params[f"path_{i}"] = path
    if section:
        conditions.append("c.section ILIKE :section")
        params["section"] = f"%{section}%"
    if clause:
        conditions.append("c.clause = :clause")
        params["clause"] = clause
    if language:
        conditions.append("c.language = :language")
        params["language"] = language
    if document_type:
        conditions.append("c.document_type = :document_type")
        params["document_type"] = document_type

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    async with get_session() as session:
        result = await session.execute(
            text(f"""
                SELECT c.id AS chunk_id, c.document_id, d.s3_path, c.content,
                       c.page_number, c.page_start, c.page_end, c.section, c.clause,
                       c.chunk_index, 1.0 AS score
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE {where_clause}
                ORDER BY d.s3_path, c.chunk_index
                LIMIT :limit
            """),
            params,
        )
        return [_row_to_result(row, "metadata", float(row.score)) for row in result.fetchall()]


async def hybrid_search(
    query: str,
    s3_paths: list[str] | None,
    top_k: int,
    similarity_threshold: float,
    ann_weight: float,
    fts_weight: float,
    metadata_weight: float,
) -> list[UnifiedRetrievalResult]:
    ann_results, fts_results, meta_results = await asyncio.gather(
        vector_search(query, top_k, similarity_threshold, s3_paths=s3_paths),
        keyword_search(query, top_k, s3_paths=s3_paths),
        metadata_search(s3_paths=s3_paths, top_k=top_k),
        return_exceptions=True,
    )
    ann_results = [] if isinstance(ann_results, Exception) else ann_results
    fts_results = [] if isinstance(fts_results, Exception) else fts_results
    meta_results = [] if isinstance(meta_results, Exception) else meta_results
    return rrf_merge(ann_results, fts_results, meta_results, ann_weight, fts_weight, metadata_weight, top_k)


def rrf_merge(
    ann_results: list[UnifiedRetrievalResult],
    fts_results: list[UnifiedRetrievalResult],
    meta_results: list[UnifiedRetrievalResult],
    ann_weight: float,
    fts_weight: float,
    meta_weight: float,
    top_k: int,
    k: int = 60,
) -> list[UnifiedRetrievalResult]:
    scores: dict[str, float] = {}
    result_map: dict[str, UnifiedRetrievalResult] = {}
    for weight, results in ((ann_weight, ann_results), (fts_weight, fts_results), (meta_weight, meta_results)):
        for rank, result in enumerate(results):
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + weight / (k + rank + 1)
            result_map.setdefault(result.chunk_id, result)
    merged = []
    for chunk_id in sorted(scores, key=scores.get, reverse=True)[:top_k]:
        result = result_map[chunk_id]
        result.score = scores[chunk_id]
        merged.append(result)
    return merged


def _path_filter_sql(s3_paths: list[str] | None) -> tuple[str, dict]:
    if not s3_paths:
        return "", {}
    placeholders = ", ".join(f":path_{i}" for i in range(len(s3_paths)))
    return f"AND d.s3_path IN ({placeholders})", {f"path_{i}": path for i, path in enumerate(s3_paths)}


def _row_to_result(row, source: str, score: float) -> UnifiedRetrievalResult:
    return UnifiedRetrievalResult(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        s3_path=row.s3_path,
        content=row.content,
        score=score,
        page_number=row.page_number,
        page_start=row.page_start,
        page_end=row.page_end,
        section=row.section,
        clause=row.clause,
        chunk_index=row.chunk_index,
        source=source,
    )
