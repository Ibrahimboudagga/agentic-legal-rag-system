from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector

from shared.config import get_database_config


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    s3_path = Column(String(512), nullable=False, unique=True)
    filename = Column(String(255), nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    total_pages = Column(Integer, nullable=False, default=0)
    total_chunks = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="pending")
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    sections = relationship("Section", back_populates="document", cascade="all, delete-orphan")
    clauses = relationship("Clause", back_populates="document", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="sections")
    clauses = relationship("Clause", back_populates="section", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("document_id", "title", name="uq_sections_document_title"),
        Index("ix_sections_document_id", "document_id"),
        Index("ix_sections_title", "title"),
    )


class Clause(Base):
    __tablename__ = "clauses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    section_id = Column(String(36), ForeignKey("sections.id", ondelete="SET NULL"), nullable=True)
    clause_number = Column(String(64), nullable=False)
    title = Column(String(255), nullable=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="clauses")
    section = relationship("Section", back_populates="clauses")

    __table_args__ = (
        UniqueConstraint("document_id", "clause_number", name="uq_clauses_document_number"),
        Index("ix_clauses_document_id", "document_id"),
        Index("ix_clauses_section_id", "section_id"),
        Index("ix_clauses_clause_number", "clause_number"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    section_id = Column(String(36), ForeignKey("sections.id", ondelete="SET NULL"), nullable=True)
    clause_id = Column(String(36), ForeignKey("clauses.id", ondelete="SET NULL"), nullable=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_tokens = Column(Integer, nullable=False, default=0)
    page_number = Column(Integer, nullable=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    section = Column(String(255), nullable=True)
    clause = Column(String(64), nullable=True)
    document_type = Column(String(64), nullable=True)
    language = Column(String(16), nullable=True)
    embedding = Column(Vector(384), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_section_id", "section_id"),
        Index("ix_chunks_clause_id", "clause_id"),
        Index("ix_chunks_page_number", "page_number"),
        Index("ix_chunks_section", "section"),
        Index("ix_chunks_clause", "clause"),
        Index("ix_chunks_language", "language"),
    )


class EmbeddingRecord(Base):
    __tablename__ = "embeddings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    chunk_id = Column(String(36), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, unique=True)
    model = Column(String(255), nullable=False)
    dimensions = Column(Integer, nullable=False)
    embedding = Column(Vector(384), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("ix_embeddings_chunk_id", "chunk_id"),)


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_id = Column(String(255), nullable=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    chunk_id = Column(String(36), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    citation_id = Column(Integer, nullable=False)
    claim = Column(Text, nullable=True)
    text_excerpt = Column(Text, nullable=False)
    retrieval_score = Column(Float, nullable=False, default=0.0)
    rerank_score = Column(Float, nullable=True)
    validation_status = Column(String(32), nullable=False, default="pending")
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_evidence_workflow_id", "workflow_id"),
        Index("ix_evidence_document_id", "document_id"),
        Index("ix_evidence_chunk_id", "chunk_id"),
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_id = Column(String(255), nullable=True, index=True)
    query = Column(Text, nullable=False)
    result_json = Column(Text, nullable=False)
    overall_risk_level = Column(String(32), nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Citation(Base):
    __tablename__ = "citations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_id = Column(String(255), nullable=True)
    evidence_id = Column(String(36), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    chunk_id = Column(String(36), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    citation_id = Column(Integer, nullable=False)
    s3_path = Column(String(512), nullable=False)
    section = Column(String(255), nullable=True)
    clause = Column(String(64), nullable=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    excerpt = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_citations_workflow_id", "workflow_id"),
        Index("ix_citations_document_id", "document_id"),
        Index("ix_citations_chunk_id", "chunk_id"),
    )


# Global engine/session factory
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        config = get_database_config()
        _engine = create_async_engine(
            config.url,
            pool_size=config.pool_size,
            max_overflow=config.pool_size * 2,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables and FTS trigger (idempotent)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_chunk_metadata_columns(conn)
        # Add search_vector tsvector column if not exists
        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'chunks' AND column_name = 'search_vector'
                ) THEN
                    ALTER TABLE chunks ADD COLUMN search_vector tsvector;
                END IF;
            END $$;
        """))
        # Create GIN index for fast FTS lookups
        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE indexname = 'ix_chunks_search_vector'
                ) THEN
                    CREATE INDEX ix_chunks_search_vector ON chunks USING gin(search_vector);
                END IF;
            END $$;
        """))
        # Create trigger to auto-populate search_vector on insert/update
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION update_search_vector() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector := to_tsvector('english', COALESCE(NEW.content, ''));
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))
        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_chunks_search_vector') THEN
                    CREATE TRIGGER trg_chunks_search_vector
                    BEFORE INSERT OR UPDATE OF content ON chunks
                    FOR EACH ROW
                    EXECUTE FUNCTION update_search_vector();
                END IF;
            END $$;
        """))


async def _ensure_chunk_metadata_columns(conn) -> None:
    columns = {
        "page_start": "INTEGER",
        "page_end": "INTEGER",
        "section_id": "VARCHAR(36)",
        "clause_id": "VARCHAR(36)",
        "section": "VARCHAR(255)",
        "clause": "VARCHAR(64)",
        "document_type": "VARCHAR(64)",
        "language": "VARCHAR(16)",
    }
    for column, column_type in columns.items():
        await conn.execute(text(f"""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'chunks' AND column_name = '{column}'
                ) THEN
                    ALTER TABLE chunks ADD COLUMN {column} {column_type};
                END IF;
            END $$;
        """))


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
