from __future__ import annotations

from evaluation.generation import citation_correctness, groundedness
from evaluation.retrieval import mrr, ndcg_at_k, precision_at_k, recall_at_k


def test_retrieval_metrics():
    retrieved = ["a", "b", "c"]
    expected = {"b", "d"}
    assert recall_at_k(retrieved, expected, 3) == 0.5
    assert precision_at_k(retrieved, expected, 2) == 0.5
    assert mrr(retrieved, expected) == 0.5
    assert 0 < ndcg_at_k(retrieved, expected, 3) <= 1


def test_generation_metrics():
    report = {
        "citations": [{"citation_id": 1}, {"citation_id": 9}],
        "detailed_findings": [{"evidence": [{"citation_id": 1}]}],
    }
    assert citation_correctness(report, {1, 2}) == 0.5
    assert groundedness(report, {1, 2}) == 1.0
