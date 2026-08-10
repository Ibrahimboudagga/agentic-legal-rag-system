from __future__ import annotations

import pytest

from agents.state import RerankedChunk, UnifiedRetrievalResult


def test_rerank_chunks_empty():
    from agents.reranker import rerank_chunks
    results = rerank_chunks("query", [], top_k=5)
    assert results == []


def test_rerank_chunks_returns_top_k():
    from agents.reranker import rerank_chunks

    chunks = [
        UnifiedRetrievalResult(
            chunk_id=f"chunk_{i}",
            document_id="doc1",
            s3_path="s3://bucket/file.pdf",
            content=f"Content about topic {i} with legal terms",
            score=0.5,
            source="ann",
        )
        for i in range(10)
    ]
    results = rerank_chunks("legal query", chunks, top_k=3)
    assert len(results) == 3


def test_rerank_chunks_returns_reranked_chunks():
    from agents.reranker import rerank_chunks

    chunks = [
        UnifiedRetrievalResult(
            chunk_id="c1",
            document_id="doc1",
            s3_path="s3://b/f.pdf",
            content="Liability clause in contract",
            score=0.8,
            source="ann",
        ),
    ]
    results = rerank_chunks("liability", chunks, top_k=5)
    assert len(results) == 1
    assert isinstance(results[0], RerankedChunk)
    assert results[0].chunk_id == "c1"
    assert results[0].rerank_score is not None
