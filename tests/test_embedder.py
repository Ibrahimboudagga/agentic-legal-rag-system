from __future__ import annotations

import os

import pytest


def test_get_embedding_dim():
    os.environ["EMBEDDING_DIM"] = "384"
    from ingestion.embedder import get_embedding_dim
    assert get_embedding_dim() == 384


def test_get_embedding_dim_custom():
    os.environ["EMBEDDING_DIM"] = "768"
    from ingestion.embedder import get_embedding_dim
    assert get_embedding_dim() == 768
    os.environ["EMBEDDING_DIM"] = "384"


def test_embed_query_returns_list():
    from ingestion.embedder import embed_query
    result = embed_query("test query")
    assert isinstance(result, list)
    assert len(result) == 384
    assert all(isinstance(x, float) for x in result)


def test_embed_texts_returns_multiple():
    from ingestion.embedder import embed_texts
    results = embed_texts(["hello", "world"])
    assert len(results) == 2
    assert len(results[0]) == 384


def test_embed_texts_empty():
    from ingestion.embedder import embed_texts
    results = embed_texts([])
    assert results == []


def test_embeddings_are_normalized():
    from ingestion.embedder import embed_query
    import math
    result = embed_query("normalized test")
    norm = math.sqrt(sum(x * x for x in result))
    assert abs(norm - 1.0) < 0.01
