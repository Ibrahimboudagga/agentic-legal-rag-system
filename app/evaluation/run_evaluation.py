from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.generation import answer_correctness, citation_correctness, groundedness
from evaluation.retrieval import mrr, ndcg_at_k, precision_at_k, recall_at_k


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def evaluate_case(case: dict, result: dict, k: int) -> dict:
    retrieved_ids = result.get("retrieved_ids", [])
    expected_ids = set(case.get("expected_chunk_ids", []))
    valid_citation_ids = set(result.get("valid_citation_ids", []))
    report = result.get("report", {})
    expected_terms = set(case.get("expected_evidence_terms", []))
    return {
        "question": case.get("question", ""),
        "recall_at_k": recall_at_k(retrieved_ids, expected_ids, k),
        "precision_at_k": precision_at_k(retrieved_ids, expected_ids, k),
        "mrr": mrr(retrieved_ids, expected_ids),
        "ndcg_at_k": ndcg_at_k(retrieved_ids, expected_ids, k),
        "citation_correctness": citation_correctness(report, valid_citation_ids),
        "groundedness": groundedness(report, valid_citation_ids),
        "answer_correctness": answer_correctness(report, expected_terms),
    }


def average_scores(rows: list[dict]) -> dict:
    if not rows:
        return {}
    metric_names = [name for name in rows[0] if name != "question"]
    return {
        name: sum(float(row.get(name, 0.0)) for row in rows) / len(rows)
        for name in metric_names
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate saved retrieval and report outputs against golden cases.")
    parser.add_argument("--golden", required=True, type=Path, help="Path to golden JSONL cases.")
    parser.add_argument("--results", required=True, type=Path, help="Path to JSONL outputs keyed by question.")
    parser.add_argument("--k", default=8, type=int)
    args = parser.parse_args()

    cases = {row["question"]: row for row in load_jsonl(args.golden)}
    results = {row["question"]: row for row in load_jsonl(args.results)}
    rows = [
        evaluate_case(case, results[question], args.k)
        for question, case in cases.items()
        if question in results
    ]
    print(json.dumps({"cases": rows, "average": average_scores(rows)}, indent=2))


if __name__ == "__main__":
    main()
