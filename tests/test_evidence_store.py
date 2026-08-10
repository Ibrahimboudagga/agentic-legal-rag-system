from __future__ import annotations

import pytest

from agents.evidence_store import EvidenceStore
from agents.state import RerankedChunk, EvidenceItem


def test_evidence_store_add_from_reranked():
    store = EvidenceStore()
    chunks = [
        RerankedChunk(
            chunk_id="c1",
            document_id="doc1",
            s3_path="s3://b/f.pdf",
            content="Liability clause",
            original_score=0.5,
            rerank_score=0.9,
            source="ann",
            page_number=1,
        ),
    ]
    items = store.add_from_reranked(chunks)
    assert len(items) == 1
    assert items[0].citation_id == 1
    assert items[0].content == "Liability clause"
    assert store.count() == 1


def test_evidence_store_deduplication():
    store = EvidenceStore()
    chunks = [
        RerankedChunk(
            chunk_id="c1",
            document_id="doc1",
            s3_path="s3://b/f.pdf",
            content="Content",
            original_score=0.5,
            rerank_score=0.9,
            source="ann",
        ),
        RerankedChunk(
            chunk_id="c1",
            document_id="doc1",
            s3_path="s3://b/f.pdf",
            content="Content duplicate",
            original_score=0.5,
            rerank_score=0.85,
            source="ann",
        ),
    ]
    items = store.add_from_reranked(chunks)
    assert len(items) == 1
    assert store.count() == 1


def test_evidence_store_add_raw():
    store = EvidenceStore()
    chunks = [
        {"chunk_id": "c1", "s3_path": "s3://b/f.pdf", "content": "Test", "score": 0.7, "source": "fts"},
    ]
    items = store.add_raw(chunks)
    assert len(items) == 1
    assert items[0].source_tool == "fts"


def test_evidence_store_get_citations():
    store = EvidenceStore()
    chunks = [
        RerankedChunk(
            chunk_id="c1",
            document_id="doc1",
            s3_path="s3://b/f.pdf",
            content="Test content here",
            original_score=0.5,
            rerank_score=0.9,
            source="ann",
            page_number=5,
        ),
    ]
    store.add_from_reranked(chunks)
    citations = store.get_citations()
    assert len(citations) == 1
    assert citations[0]["page_number"] == 5
    assert citations[0]["citation_id"] == 1


def test_evidence_store_get_evidence_context():
    store = EvidenceStore()
    chunks = [
        RerankedChunk(
            chunk_id="c1",
            document_id="doc1",
            s3_path="s3://b/f.pdf",
            content="Legal clause about indemnification",
            original_score=0.5,
            rerank_score=0.9,
            source="ann",
            page_number=3,
        ),
    ]
    store.add_from_reranked(chunks)
    context = store.get_evidence_context()
    assert "Citation 1" in context
    assert "indemnification" in context


def test_evidence_store_clear():
    store = EvidenceStore()
    chunks = [
        RerankedChunk(
            chunk_id="c1",
            document_id="doc1",
            s3_path="s3://b/f.pdf",
            content="Test",
            original_score=0.5,
            rerank_score=0.9,
            source="ann",
        ),
    ]
    store.add_from_reranked(chunks)
    assert store.count() == 1
    store.clear()
    assert store.count() == 0


def test_evidence_store_citation_counter_increments():
    store = EvidenceStore()
    chunks = [
        RerankedChunk(
            chunk_id=f"c{i}",
            document_id="doc1",
            s3_path="s3://b/f.pdf",
            content=f"Content {i}",
            original_score=0.5,
            rerank_score=0.9,
            source="ann",
        )
        for i in range(5)
    ]
    items = store.add_from_reranked(chunks)
    assert [item.citation_id for item in items] == [1, 2, 3, 4, 5]
