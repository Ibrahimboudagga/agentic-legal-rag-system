from __future__ import annotations

import os

import pytest

from agents.evidence_store import EvidenceStore
from agents.evidence_validator import validate_evidence, _check_consistency
from agents.state import RerankedChunk, ValidationIssue


def _make_store_with_chunks(chunks_data: list[dict]) -> EvidenceStore:
    store = EvidenceStore()
    chunks = [
        RerankedChunk(
            chunk_id=c["chunk_id"],
            document_id="doc1",
            s3_path=c.get("s3_path", "s3://b/f.pdf"),
            content=c.get("content", "test content"),
            original_score=0.5,
            rerank_score=c.get("rerank_score", 0.8),
            source="ann",
        )
        for c in chunks_data
    ]
    store.add_from_reranked(chunks)
    return store


def test_validate_no_evidence():
    store = EvidenceStore()
    result = validate_evidence("test query", store)
    assert result.passed is False
    assert result.needs_retrieval is True
    assert any(i.issue_type == "no_evidence" for i in result.issues)


def test_validate_sufficient_evidence():
    chunks = [
        {"chunk_id": f"c{i}", "content": f"Contract clause about liability and indemnification {i}", "rerank_score": 0.8}
        for i in range(5)
    ]
    store = _make_store_with_chunks(chunks)
    os.environ["MIN_EVIDENCE_COUNT"] = "3"
    result = validate_evidence("contract liability indemnification", store)
    assert result.passed is True
    assert result.needs_retrieval is False


def test_validate_insufficient_evidence():
    chunks = [
        {"chunk_id": "c1", "content": "Single clause", "rerank_score": 0.8},
    ]
    store = _make_store_with_chunks(chunks)
    os.environ["MIN_EVIDENCE_COUNT"] = "3"
    result = validate_evidence("contract liability", store)
    assert result.passed is False
    assert any(i.issue_type == "insufficient" for i in result.issues)


def test_validate_coverage_check():
    chunks = [
        {"chunk_id": f"c{i}", "content": "xyzzy unrelated content here", "rerank_score": 0.8}
        for i in range(5)
    ]
    store = _make_store_with_chunks(chunks)
    os.environ["MIN_EVIDENCE_COUNT"] = "2"
    result = validate_evidence("contract liability", store)
    assert result.coverage_score < 0.5


def test_validate_single_source():
    chunks = [
        {"chunk_id": f"c{i}", "s3_path": "s3://same/file.pdf", "content": f"clause {i}", "rerank_score": 0.8}
        for i in range(5)
    ]
    store = _make_store_with_chunks(chunks)
    os.environ["MIN_EVIDENCE_COUNT"] = "2"
    result = validate_evidence("clause", store)
    assert any(i.issue_type == "single_source" for i in result.issues)


def test_validate_multiple_sources_no_warning():
    chunks = [
        {"chunk_id": f"c{i}", "s3_path": f"s3://bucket/file_{i}.pdf", "content": f"clause {i}", "rerank_score": 0.8}
        for i in range(4)
    ]
    store = _make_store_with_chunks(chunks)
    os.environ["MIN_EVIDENCE_COUNT"] = "2"
    result = validate_evidence("clause", store)
    assert not any(i.issue_type == "single_source" for i in result.issues)


def test_validate_low_relevance():
    chunks = [
        {"chunk_id": f"c{i}", "content": f"clause {i}", "rerank_score": 0.1}
        for i in range(5)
    ]
    store = _make_store_with_chunks(chunks)
    os.environ["MIN_EVIDENCE_COUNT"] = "2"
    result = validate_evidence("clause", store)
    assert any(i.issue_type == "low_relevance" for i in result.issues)


def test_check_consistency_all_positive():
    items = [
        RerankedChunk(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="The contract shall apply", original_score=0.5, rerank_score=0.8, source="ann"),
        RerankedChunk(chunk_id="c2", document_id="d1", s3_path="s3://b/f.pdf", content="This clause is valid", original_score=0.5, rerank_score=0.8, source="ann"),
    ]
    score = _check_consistency(items)
    assert score == 1.0


def test_check_consistency_all_negative():
    items = [
        RerankedChunk(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="The contract shall not apply", original_score=0.5, rerank_score=0.8, source="ann"),
        RerankedChunk(chunk_id="c2", document_id="d1", s3_path="s3://b/f.pdf", content="This clause does not exist", original_score=0.5, rerank_score=0.8, source="ann"),
    ]
    score = _check_consistency(items)
    assert score == 1.0


def test_check_consistency_mixed():
    items = [
        RerankedChunk(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="The contract shall apply", original_score=0.5, rerank_score=0.8, source="ann"),
        RerankedChunk(chunk_id="c2", document_id="d1", s3_path="s3://b/f.pdf", content="This clause shall not apply", original_score=0.5, rerank_score=0.8, source="ann"),
    ]
    score = _check_consistency(items)
    assert 0.4 <= score <= 0.6


def test_check_consistency_single_item():
    items = [
        RerankedChunk(chunk_id="c1", document_id="d1", s3_path="s3://b/f.pdf", content="Single item", original_score=0.5, rerank_score=0.8, source="ann"),
    ]
    score = _check_consistency(items)
    assert score == 1.0
