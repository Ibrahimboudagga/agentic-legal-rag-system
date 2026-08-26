from __future__ import annotations

import os
from collections import Counter

from agents.evidence_store import EvidenceStore
from agents.state import ValidationResult, ValidationIssue


def validate_evidence(
    query: str,
    evidence_store: EvidenceStore,
    analysis_focus: list[str] | None = None,
) -> ValidationResult:
    """Deterministic evidence validation.

    No LLM involved. Uses heuristic checks:
    1. SUFFICIENCY: minimum evidence count
    2. COVERAGE: keyword overlap between query and evidence
    3. SOURCE DIVERSITY: multiple documents/sources represented
    4. RELEVANCE: average relevance score threshold
    5. CONSISTENCY: detect obvious contradictions via keyword conflicts
    """
    items = evidence_store.get_all()

    if not items:
        return ValidationResult(
            passed=False,
            coverage_score=0.0,
            consistency_score=0.0,
            supported=False,
            confidence=0.0,
            reason="No retrieved evidence is available to support the claim.",
            issues=[ValidationIssue(
                issue_type="no_evidence",
                description="No evidence items found for the query.",
                severity="critical",
            )],
            suggestions=["Broaden the search query", "Check if documents are indexed"],
            missing_information=["Any clause or section relevant to the user query"],
            needs_retrieval=True,
        )

    issues: list[ValidationIssue] = []

    # 1. Sufficiency check
    min_evidence = int(os.getenv("MIN_EVIDENCE_COUNT", "3"))
    sufficient_count = len(items) >= min_evidence
    if not sufficient_count:
        issues.append(ValidationIssue(
            issue_type="insufficient",
            description=f"Only {len(items)} evidence items found, minimum is {min_evidence}.",
            severity="high",
        ))

    # 2. Coverage check (keyword overlap)
    query_keywords = set(query.lower().split())
    evidence_text = " ".join(item.content.lower() for item in items)
    evidence_words = set(evidence_text.split())
    overlap = query_keywords & evidence_words
    coverage_score = len(overlap) / max(len(query_keywords), 1)

    if coverage_score < 0.3:
        issues.append(ValidationIssue(
            issue_type="coverage_gap",
            description=f"Low keyword coverage: {coverage_score:.2f}. Query terms not found in evidence.",
            severity="medium",
        ))

    # 3. Source diversity check
    sources = [item.s3_path for item in items]
    unique_sources = len(set(sources))
    source_diversity = unique_sources / max(len(sources), 1)

    if unique_sources < 2 and len(items) > 2:
        issues.append(ValidationIssue(
            issue_type="single_source",
            description=f"All {len(items)} evidence items from {unique_sources} source(s).",
            severity="medium",
        ))

    # 4. Relevance score check
    scores = [item.relevance_score for item in items]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    low_score_items = [s for s in scores if s < 0.3]
    if len(low_score_items) > len(scores) * 0.5:
        issues.append(ValidationIssue(
            issue_type="low_relevance",
            description=f"{len(low_score_items)}/{len(scores)} items have relevance < 0.3.",
            severity="medium",
        ))

    # 5. Consistency check (simple keyword contradiction detection)
    consistency_score = _check_consistency(items)
    if consistency_score < 0.7:
        issues.append(ValidationIssue(
            issue_type="contradiction",
            description=f"Potential inconsistencies detected (score: {consistency_score:.2f}).",
            severity="high",
        ))

    # Determine pass/fail
    critical_issues = [i for i in issues if i.severity in ("critical", "high")]
    passed = len(critical_issues) == 0 and sufficient_count
    needs_retrieval = len(critical_issues) > 0 and len(items) < min_evidence * 2

    suggestions = []
    missing_information = []
    if not sufficient_count:
        suggestions.append("Retrieve more evidence")
        missing_information.append("additional corroborating evidence")
    if coverage_score < 0.3:
        suggestions.append("Try different search terms")
        missing_information.extend(sorted(query_keywords - evidence_words)[:5])
    if unique_sources < 2:
        suggestions.append("Search across more documents")
        missing_information.append("evidence from additional contracts")

    confidence = max(0.0, min(1.0, (coverage_score * 0.45) + (consistency_score * 0.35) + (min(avg_score, 1.0) * 0.20)))
    supported = passed and confidence >= 0.5
    if supported:
        reason = f"Evidence passed sufficiency checks with coverage {coverage_score:.2f}, consistency {consistency_score:.2f}, and average relevance {avg_score:.2f}."
    else:
        reason = "; ".join(issue.description for issue in issues) or "Evidence did not meet support thresholds."

    return ValidationResult(
        passed=passed,
        coverage_score=coverage_score,
        consistency_score=consistency_score,
        supported=supported,
        confidence=round(confidence, 3),
        reason=reason,
        issues=issues,
        suggestions=suggestions,
        missing_information=missing_information,
        needs_retrieval=needs_retrieval,
    )


def _check_consistency(items: list) -> float:
    """Simple consistency check based on keyword patterns.

    Looks for negation patterns that might indicate contradictions.
    Returns a score between 0.0 (inconsistent) and 1.0 (consistent).
    """
    if len(items) < 2:
        return 1.0

    negation_patterns = ["not ", "no ", "never ", "shall not", "does not", "is not"]
    pos_count = 0
    neg_count = 0

    for item in items:
        content_lower = item.content.lower()
        has_negation = any(p in content_lower for p in negation_patterns)
        if has_negation:
            neg_count += 1
        else:
            pos_count += 1

    total = pos_count + neg_count
    if total == 0:
        return 1.0

    majority_ratio = max(pos_count, neg_count) / total
    return majority_ratio
