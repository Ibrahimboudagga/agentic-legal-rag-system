from __future__ import annotations

from dataclasses import dataclass, field

from agents.state import EvidenceItem, RerankedChunk


class EvidenceStore:
    """Accumulates and manages evidence items throughout the agent workflow.

    Evidence is built incrementally as retrieval, reranking, and validation
    proceed. Each item gets a citation ID for downstream referencing.
    """

    def __init__(self):
        self._items: list[EvidenceItem] = []
        self._citation_counter: int = 0
        self._seen_chunk_ids: set[str] = set()

    def add_from_reranked(self, chunks: list[RerankedChunk]) -> list[EvidenceItem]:
        """Add reranked chunks as evidence items. Deduplicates by chunk_id."""
        new_items = []
        for chunk in chunks:
            if chunk.chunk_id in self._seen_chunk_ids:
                continue
            self._citation_counter += 1
            item = EvidenceItem(
                chunk_id=chunk.chunk_id,
                s3_path=chunk.s3_path,
                content=chunk.content,
                page_number=chunk.page_number,
                relevance_score=chunk.rerank_score,
                citation_id=self._citation_counter,
                source_tool=chunk.source,
                validation_status="validated",
            )
            self._items.append(item)
            self._seen_chunk_ids.add(chunk.chunk_id)
            new_items.append(item)
        return new_items

    def add_raw(self, chunks: list[dict]) -> list[EvidenceItem]:
        """Add raw chunk dicts as evidence (for fallback paths)."""
        new_items = []
        for chunk in chunks:
            cid = chunk.get("chunk_id", "")
            if cid in self._seen_chunk_ids:
                continue
            self._citation_counter += 1
            item = EvidenceItem(
                chunk_id=cid,
                s3_path=chunk.get("s3_path", ""),
                content=chunk.get("content", ""),
                page_number=chunk.get("page_number"),
                relevance_score=chunk.get("score", 0.0),
                citation_id=self._citation_counter,
                source_tool=chunk.get("source", ""),
                validation_status="validated",
            )
            self._items.append(item)
            if cid:
                self._seen_chunk_ids.add(cid)
            new_items.append(item)
        return new_items

    def get_all(self) -> list[EvidenceItem]:
        return list(self._items)

    def get_citations(self) -> list[dict]:
        return [
            {
                "citation_id": item.citation_id,
                "s3_path": item.s3_path,
                "page_number": item.page_number,
                "content": item.content[:300],
                "source_tool": item.source_tool,
                "relevance_score": item.relevance_score,
            }
            for item in self._items
        ]

    def get_evidence_context(self) -> str:
        """Build a context string from all evidence for LLM prompts."""
        parts = []
        for item in self._items:
            parts.append(
                f"[Citation {item.citation_id}: {item.s3_path} | "
                f"Page {item.page_number or 'N/A'} | "
                f"Score: {item.relevance_score:.3f}]\n{item.content}"
            )
        return "\n\n---\n\n".join(parts)

    def count(self) -> int:
        return len(self._items)

    def clear(self):
        self._items.clear()
        self._seen_chunk_ids.clear()
        self._citation_counter = 0
