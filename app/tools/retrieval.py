from __future__ import annotations

from agents.state import UnifiedRetrievalResult
from retrieval import service
from shared.config import get_rag_config


async def search_hybrid(
    query: str,
    s3_paths: list[str] | None = None,
    top_k: int | None = None,
) -> list[UnifiedRetrievalResult]:
    cfg = get_rag_config()
    return await service.hybrid_search(
        query=query,
        s3_paths=s3_paths,
        top_k=top_k or cfg.retrieval_top_k,
        similarity_threshold=cfg.similarity_threshold,
        ann_weight=cfg.semantic_weight,
        fts_weight=cfg.keyword_weight,
        metadata_weight=cfg.metadata_weight,
    )


async def search_vector(query: str, top_k: int | None = None, s3_paths: list[str] | None = None) -> list[UnifiedRetrievalResult]:
    cfg = get_rag_config()
    return await service.vector_search(query, top_k or cfg.retrieval_top_k, cfg.similarity_threshold, s3_paths=s3_paths)


async def search_keyword(query: str, top_k: int | None = None, s3_paths: list[str] | None = None) -> list[UnifiedRetrievalResult]:
    return await service.keyword_search(query, top_k or get_rag_config().retrieval_top_k, s3_paths=s3_paths)


async def filter_metadata(
    s3_paths: list[str] | None = None,
    section: str | None = None,
    clause: str | None = None,
    language: str | None = None,
    document_type: str | None = None,
    top_k: int | None = None,
) -> list[UnifiedRetrievalResult]:
    return await service.metadata_search(
        s3_paths=s3_paths,
        top_k=top_k or get_rag_config().retrieval_top_k,
        section=section,
        clause=clause,
        language=language,
        document_type=document_type,
    )
