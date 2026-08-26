from __future__ import annotations

import json
from typing import Any

from shared.database import AnalysisResult, Citation, EvidenceRecord, get_session


async def persist_agent_run(
    *,
    workflow_id: str | None,
    query: str,
    analysis: dict[str, Any],
    synthesis: dict[str, Any],
    evidence: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> None:
    """Persist an agent run's evidence, citations, and final analysis output."""
    async with get_session() as session:
        session.add(
            AnalysisResult(
                workflow_id=workflow_id,
                query=query,
                result_json=json.dumps(
                    {
                        "analysis": analysis,
                        "synthesis": synthesis,
                    },
                    ensure_ascii=True,
                    default=str,
                ),
                overall_risk_level=synthesis.get("overall_risk_level") or analysis.get("overall_risk_level"),
                confidence=analysis.get("confidence"),
            )
        )

        evidence_by_citation: dict[int, EvidenceRecord] = {}
        for item in evidence:
            record = EvidenceRecord(
                workflow_id=workflow_id,
                document_id=item.get("document_id") or None,
                chunk_id=item.get("chunk_id") or None,
                citation_id=int(item.get("citation_id") or 0),
                claim=None,
                text_excerpt=item.get("content") or "",
                retrieval_score=float(item.get("relevance_score") or 0.0),
                rerank_score=float(item.get("rerank_score")) if item.get("rerank_score") is not None else None,
                validation_status=item.get("validation_status") or "pending",
                metadata_json=json.dumps(
                    {
                        "s3_path": item.get("s3_path"),
                        "section": item.get("section"),
                        "clause": item.get("clause"),
                        "page_number": item.get("page_number"),
                        "page_start": item.get("page_start"),
                        "page_end": item.get("page_end"),
                        "source_tool": item.get("source_tool"),
                    },
                    ensure_ascii=True,
                    default=str,
                ),
            )
            session.add(record)
            evidence_by_citation[record.citation_id] = record

        await session.flush()

        citation_rows = citations or _citations_from_evidence(evidence)
        for citation in citation_rows:
            citation_id = int(citation.get("citation_id") or 0)
            evidence_record = evidence_by_citation.get(citation_id)
            session.add(
                Citation(
                    workflow_id=workflow_id,
                    evidence_id=evidence_record.id if evidence_record else None,
                    document_id=citation.get("document_id") or (evidence_record.document_id if evidence_record else None),
                    chunk_id=citation.get("chunk_id") or (evidence_record.chunk_id if evidence_record else None),
                    citation_id=citation_id,
                    s3_path=citation.get("s3_path") or "",
                    section=citation.get("section"),
                    clause=citation.get("clause"),
                    page_start=citation.get("page_start") or citation.get("page_number"),
                    page_end=citation.get("page_end") or citation.get("page_number"),
                    excerpt=citation.get("excerpt") or citation.get("content") or "",
                )
            )


def _citations_from_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "citation_id": item.get("citation_id"),
            "document_id": item.get("document_id"),
            "chunk_id": item.get("chunk_id"),
            "s3_path": item.get("s3_path"),
            "section": item.get("section"),
            "clause": item.get("clause"),
            "page_start": item.get("page_start"),
            "page_end": item.get("page_end"),
            "excerpt": item.get("content"),
        }
        for item in evidence
    ]
