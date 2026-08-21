from __future__ import annotations

import pytest

try:
    from retrieval.hybrid_search import (
        _reciprocal_rank_fusion,
        HybridSearchConfig,
    )
    from retrieval.vector_store import SearchResult
    HAS_PGVVECTOR = True
except (ImportError, ModuleNotFoundError):
    HAS_PGVVECTOR = False

pytestmark = pytest.mark.skipif(not HAS_PGVVECTOR, reason="pgvector not installed")


def test_reciprocal_rank_fusion_semantic_only():
    semantic = [
        SearchResult(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="A", score=0.9),
        SearchResult(chunk_id="c2", document_id="d1", s3_path="s3://b/f.pdf", content="B", score=0.8),
    ]
    keyword = []
    merged = _reciprocal_rank_fusion(semantic, keyword)
    assert len(merged) == 2
    assert merged[0].chunk_id == "c1"


def test_reciprocal_rank_fusion_keyword_only():
    semantic = []
    keyword = [
        SearchResult(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="A", score=0.9),
        SearchResult(chunk_id="c2", document_id="d1", s3_path="s3://b/f.pdf", content="B", score=0.8),
    ]
    merged = _reciprocal_rank_fusion(semantic, keyword)
    assert len(merged) == 2
    assert merged[0].chunk_id == "c1"


def test_reciprocal_rank_fusion_merges_overlap():
    semantic = [
        SearchResult(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="A", score=0.9),
        SearchResult(chunk_id="c2", document_id="d1", s3_path="s3://b/f.pdf", content="B", score=0.8),
    ]
    keyword = [
        SearchResult(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="A", score=0.7),
        SearchResult(chunk_id="c3", document_id="d1", s3_path="s3://b/f.pdf", content="C", score=0.6),
    ]
    merged = _reciprocal_rank_fusion(semantic, keyword)
    chunk_ids = [r.chunk_id for r in merged]
    assert "c1" in chunk_ids
    assert "c2" in chunk_ids
    assert "c3" in chunk_ids
    assert len(merged) == 3


def test_reciprocal_rank_fusion_respects_weights():
    semantic = [
        SearchResult(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="A", score=0.9),
    ]
    keyword = [
        SearchResult(chunk_id="c2", document_id="d1", s3_path="s3://b/f.pdf", content="B", score=0.9),
    ]
    merged_high_semantic = _reciprocal_rank_fusion(semantic, keyword, semantic_weight=0.9, keyword_weight=0.1)
    assert merged_high_semantic[0].chunk_id == "c1"

    merged_high_keyword = _reciprocal_rank_fusion(semantic, keyword, semantic_weight=0.1, keyword_weight=0.9)
    assert merged_high_keyword[0].chunk_id == "c2"


def test_reciprocal_rank_fusion_empty():
    merged = _reciprocal_rank_fusion([], [])
    assert merged == []


def test_hybrid_search_config_defaults():
    config = HybridSearchConfig()
    assert config.semantic_top_k == 10
    assert config.keyword_top_k == 10
    assert config.final_top_k == 5
    assert config.semantic_weight == 0.7
    assert config.keyword_weight == 0.3
