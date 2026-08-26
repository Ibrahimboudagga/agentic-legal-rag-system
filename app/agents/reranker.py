from __future__ import annotations

from functools import lru_cache

from agents.state import RerankedChunk, UnifiedRetrievalResult


@lru_cache(maxsize=1)
def _get_cross_encoder():
    """Lazy-load the cross-encoder reranking model.

    Uses cross-encoder/ms-marco-MiniLM-L-6-v2 by default.
    This is a small, fast model trained on MS MARCO passage ranking.
    Runs locally — no API calls, no LLM involved.
    """
    from sentence_transformers import CrossEncoder

    from shared.config import get_rag_config

    model_name = get_rag_config().reranker_model
    return CrossEncoder(model_name)


def rerank_chunks(
    query: str,
    chunks: list[UnifiedRetrievalResult],
    top_k: int = 5,
) -> list[RerankedChunk]:
    """Deterministic reranking using a cross-encoder model.

    No LLM involved. Uses a trained cross-encoder to score
    query-document relevance. Runs entirely locally.
    """
    if not chunks:
        return []

    model = _get_cross_encoder()

    pairs = [(query, chunk.content[:512]) for chunk in chunks]
    scores = model.predict(pairs, show_progress_bar=False)

    scored = list(zip(chunks, scores))
    scored.sort(key=lambda x: x[1], reverse=True)

    results = []
    for chunk, score in scored[:top_k]:
        results.append(
            RerankedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                s3_path=chunk.s3_path,
                content=chunk.content,
                original_score=chunk.score,
                rerank_score=float(score),
                source=chunk.source,
                page_number=chunk.page_number,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section=chunk.section,
                clause=chunk.clause,
                chunk_index=chunk.chunk_index,
            )
        )

    return results
