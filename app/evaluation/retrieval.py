from __future__ import annotations


def recall_at_k(retrieved_ids: list[str], expected_ids: set[str], k: int) -> float:
    if not expected_ids:
        return 1.0
    hits = set(retrieved_ids[:k]) & expected_ids
    return len(hits) / len(expected_ids)


def precision_at_k(retrieved_ids: list[str], expected_ids: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    hits = set(retrieved_ids[:k]) & expected_ids
    return len(hits) / k


def mrr(retrieved_ids: list[str], expected_ids: set[str]) -> float:
    for index, retrieved_id in enumerate(retrieved_ids, start=1):
        if retrieved_id in expected_ids:
            return 1 / index
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], expected_ids: set[str], k: int) -> float:
    dcg = 0.0
    for index, retrieved_id in enumerate(retrieved_ids[:k], start=1):
        if retrieved_id in expected_ids:
            import math

            dcg += 1 / math.log2(index + 1)
    ideal_hits = min(len(expected_ids), k)
    if ideal_hits == 0:
        return 1.0
    import math

    ideal_dcg = sum(1 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / ideal_dcg
