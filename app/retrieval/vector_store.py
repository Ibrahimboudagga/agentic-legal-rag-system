from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import Chunk, Document, get_session


@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    s3_path: str
    content: str
    score: float
    page_number: int | None = None
    chunk_index: int = 0
    section: str | None = None
    clause: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict = field(default_factory=dict)


async def store_document(
    session: AsyncSession,
    s3_path: str,
    filename: str,
    content_hash: str,
    total_pages: int,
    total_chunks: int,
    metadata_json: str | None = None,
) -> Document:
    """Insert or get existing document by content_hash."""
    existing = await session.execute(
        text("SELECT id FROM documents WHERE content_hash = :hash"),
        {"hash": content_hash},
    )
    row = existing.first()
    if row:
        doc = await session.get(Document, row[0])
        if doc:
            return doc

    doc = Document(
        s3_path=s3_path,
        filename=filename,
        content_hash=content_hash,
        total_pages=total_pages,
        total_chunks=total_chunks,
        status="ready",
        metadata_json=metadata_json,
    )
    session.add(doc)
    await session.flush()
    return doc


async def store_chunks(
    session: AsyncSession,
    document_id: str,
    chunks: list[dict],
) -> list[Chunk]:
    """Bulk insert chunks with embeddings.

    Each chunk dict must have: content, chunk_index, embedding, and optional page_number.
    """
    db_chunks = []
    for c in chunks:
        chunk = Chunk(
            document_id=document_id,
            chunk_index=c["chunk_index"],
            content=c["content"],
            content_tokens=c.get("content_tokens", len(c["content"]) // 4),
            page_number=c.get("page_number"),
            page_start=c.get("page_start") or c.get("page_number"),
            page_end=c.get("page_end") or c.get("page_number"),
            section=c.get("section"),
            clause=c.get("clause"),
            document_type=c.get("document_type"),
            language=c.get("language"),
            embedding=c["embedding"],
            metadata_json=c.get("metadata_json"),
        )
        session.add(chunk)
        db_chunks.append(chunk)
    await session.flush()
    return db_chunks


async def search_semantic(
    session: AsyncSession,
    query_embedding: list[float],
    top_k: int = 10,
    similarity_threshold: float = 0.3,
) -> list[SearchResult]:
    """Cosine similarity search via pgvector <=> operator."""
    result = await session.execute(
        text("""
            SELECT
                c.id AS chunk_id,
                c.document_id,
                d.s3_path,
                c.content,
                c.page_number,
                c.page_start,
                c.page_end,
                c.section,
                c.clause,
                c.chunk_index,
                1 - (c.embedding <=> :embedding::vector) AS similarity
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.embedding IS NOT NULL
              AND 1 - (c.embedding <=> :embedding::vector) > :threshold
            ORDER BY c.embedding <=> :embedding::vector
            LIMIT :limit
        """),
        {
            "embedding": str(query_embedding),
            "threshold": similarity_threshold,
            "limit": top_k,
        },
    )

    return [
        SearchResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            s3_path=row.s3_path,
            content=row.content,
            score=float(row.similarity),
            page_number=row.page_number,
            page_start=row.page_start,
            page_end=row.page_end,
            section=row.section,
            clause=row.clause,
            chunk_index=row.chunk_index,
        )
        for row in result.fetchall()
    ]


async def search_keyword(
    session: AsyncSession,
    query: str,
    top_k: int = 10,
) -> list[SearchResult]:
    """PostgreSQL full-text search with ts_rank."""
    result = await session.execute(
        text("""
            SELECT
                c.id AS chunk_id,
                c.document_id,
                d.s3_path,
                c.content,
                c.page_number,
                c.page_start,
                c.page_end,
                c.section,
                c.clause,
                c.chunk_index,
                ts_rank_cd(c.search_vector, plainto_tsquery('english', :query)) AS rank
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.search_vector @@ plainto_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :limit
        """),
        {"query": query, "limit": top_k},
    )

    return [
        SearchResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            s3_path=row.s3_path,
            content=row.content,
            score=float(row.rank),
            page_number=row.page_number,
            page_start=row.page_start,
            page_end=row.page_end,
            section=row.section,
            clause=row.clause,
            chunk_index=row.chunk_index,
        )
        for row in result.fetchall()
    ]


async def get_document_chunks(
    session: AsyncSession,
    document_id: str,
) -> list[Chunk]:
    """Get all chunks for a document."""
    result = await session.execute(
        text("""
            SELECT id, content, chunk_index, page_number, page_start, page_end, section, clause, content_tokens
            FROM chunks
            WHERE document_id = :doc_id
            ORDER BY chunk_index
        """),
        {"doc_id": document_id},
    )

    return [
        Chunk(
            id=row.id,
            document_id=document_id,
            chunk_index=row.chunk_index,
            content=row.content,
            content_tokens=row.content_tokens,
            page_number=row.page_number,
            page_start=row.page_start,
            page_end=row.page_end,
            section=row.section,
            clause=row.clause,
        )
        for row in result.fetchall()
    ]


async def document_exists(session: AsyncSession, content_hash: str) -> bool:
    """Check if a document with this content hash already exists."""
    result = await session.execute(
        text("SELECT 1 FROM documents WHERE content_hash = :hash"),
        {"hash": content_hash},
    )
    return result.first() is not None
