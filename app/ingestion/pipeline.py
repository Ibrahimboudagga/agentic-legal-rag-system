from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import fitz
import pymupdf4llm

from shared.config import get_app_config, get_aws_config
from shared.s3 import get_s3_client, parse_s3_path, extract_s3_filename
from shared.database import get_session, init_db
from ingestion.chunker import chunk_markdown
from ingestion.embedder import embed_texts
from retrieval.vector_store import store_document, store_chunks


@dataclass
class IngestionResult:
    document_id: str
    s3_path: str
    total_chunks: int
    total_pages: int
    duration_seconds: float


async def ingest_document(
    s3_path: str,
    batch_size: int = 2,
    max_chunk_tokens: int = 512,
) -> IngestionResult:
    """Full ingestion pipeline: download PDF -> extract markdown -> chunk -> embed -> store in pgvector.

    This runs outside of Temporal as a direct async function.
    For Temporal integration, wrap this in an activity.
    """
    start = time.monotonic()

    app_config = get_app_config()
    aws_config = get_aws_config()

    await init_db()

    s3_client = get_s3_client(aws_config)
    bucket, key = parse_s3_path(s3_path)
    filename = extract_s3_filename(s3_path)
    local_path = os.path.join(app_config.temp_dir, filename)

    os.makedirs(app_config.temp_dir, exist_ok=True)

    await asyncio.to_thread(s3_client.download_file, bucket, key, local_path)

    content_hash = await asyncio.to_thread(_file_hash, local_path)

    doc = await asyncio.to_thread(fitz.open, local_path)
    total_pages = doc.page_count

    try:
        markdown_text = await asyncio.to_thread(
            _extract_markdown, doc, batch_size
        )
    finally:
        doc.close()

    try:
        os.remove(local_path)
    except OSError:
        pass

    chunks = chunk_markdown(markdown_text, max_chunk_tokens=max_chunk_tokens)

    if not chunks:
        raise ValueError(f"No chunks extracted from {s3_path}")

    chunk_texts = [c.content for c in chunks]
    embeddings = await asyncio.to_thread(embed_texts, chunk_texts)

    async with get_session() as session:
        document = await store_document(
            session,
            s3_path=s3_path,
            filename=filename,
            content_hash=content_hash,
            total_pages=total_pages,
            total_chunks=len(chunks),
        )

        chunk_data = [
            {
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "content_tokens": len(chunk.content) // 4,
                "embedding": embedding,
                "metadata_json": json.dumps({
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    **chunk.metadata,
                }),
            }
            for chunk, embedding in zip(chunks, embeddings)
        ]

        await store_chunks(session, document.id, chunk_data)

    duration = time.monotonic() - start

    return IngestionResult(
        document_id=document.id,
        s3_path=s3_path,
        total_chunks=len(chunks),
        total_pages=total_pages,
        duration_seconds=round(duration, 3),
    )


def _extract_markdown(doc: fitz.Document, batch_size: int) -> str:
    """Extract markdown from PDF in batches."""
    total_pages = doc.page_count
    all_chunks = []
    for start in range(0, total_pages, batch_size):
        end = min(start + batch_size, total_pages)
        batch_md = pymupdf4llm.to_markdown(doc, from_page=start, to_page=end)
        all_chunks.append(batch_md)
    return "\n\n".join(all_chunks)


def _file_hash(path: str) -> str:
    """SHA-256 hash of file content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
