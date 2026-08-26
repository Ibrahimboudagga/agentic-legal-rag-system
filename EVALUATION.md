# Evaluation

The first evaluation layer is local and Python-based. It avoids an external evaluation platform while the architecture is still evolving.

## Golden Dataset

Seed examples live in:

`app/evaluation/datasets/golden_contract_questions.jsonl`

Each row contains:

- question
- expected document
- expected clause
- expected evidence terms
- expected answer notes

## Retrieval Metrics

`app/evaluation/retrieval.py` implements:

- `recall_at_k`
- `precision_at_k`
- `mrr`
- `ndcg_at_k`

These can be used after retrieval runs by comparing retrieved chunk IDs against expected chunk IDs or expected evidence labels.

## Generation Metrics

`app/evaluation/generation.py` implements:

- citation correctness
- groundedness by finding-level evidence references
- answer correctness by expected evidence terms

These checks are intentionally deterministic. They validate whether generated reports cite evidence that actually exists in the retrieved evidence set.

## Running Saved Evaluations

Use the lightweight runner when you have saved retrieval/report outputs:

```powershell
python -m evaluation.run_evaluation --golden app/evaluation/datasets/golden_contract_questions.jsonl --results outputs/eval_results.jsonl --k 8
```

The results JSONL should include `question`, `retrieved_ids`, `valid_citation_ids`, and `report` fields. The runner is intentionally offline; it evaluates saved outputs instead of starting Temporal or ingesting PDFs.

## Current Limitations

The repository now has deterministic metrics, seed data, and a saved-output runner. It does not yet include a full end-to-end evaluation command that starts Temporal, ingests PDFs, executes reviews, and writes aggregate reports. That should be the next step once the local dependency environment and PostgreSQL service are consistently available.
