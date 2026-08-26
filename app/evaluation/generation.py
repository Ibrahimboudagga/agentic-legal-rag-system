from __future__ import annotations


def citation_correctness(report: dict, valid_citation_ids: set[int]) -> float:
    citations = report.get("citations", [])
    if not citations:
        return 1.0 if not valid_citation_ids else 0.0
    correct = [
        citation for citation in citations
        if citation.get("citation_id") in valid_citation_ids
    ]
    return len(correct) / len(citations)


def groundedness(report: dict, valid_citation_ids: set[int]) -> float:
    findings = report.get("detailed_findings", [])
    if not findings:
        return 0.0
    grounded = 0
    for finding in findings:
        evidence = finding.get("evidence", [])
        if any(item.get("citation_id") in valid_citation_ids for item in evidence):
            grounded += 1
    return grounded / len(findings)


def answer_correctness(report: dict, expected_terms: set[str]) -> float:
    if not expected_terms:
        return 1.0
    text_parts = [
        report.get("executive_summary", ""),
        report.get("risk_justification", ""),
        str(report.get("detailed_findings", "")),
        str(report.get("recommendations", "")),
    ]
    answer_text = " ".join(text_parts).lower()
    matched = [term for term in expected_terms if term.lower() in answer_text]
    return len(matched) / len(expected_terms)
