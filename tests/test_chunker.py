from __future__ import annotations

import pytest

from ingestion.chunker import chunk_markdown, estimate_tokens, TextChunk


def test_chunk_markdown_empty():
    assert chunk_markdown("") == []
    assert chunk_markdown("   ") == []


def test_chunk_markdown_short_text():
    text = "This is a short contract clause about indemnification."
    chunks = chunk_markdown(text, max_chunk_tokens=100)
    assert len(chunks) >= 1
    assert chunks[0].content.strip() != ""
    assert chunks[0].chunk_index == 0


def test_chunk_markdown_long_text():
    paragraphs = [f"Paragraph {i}. " * 50 for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_markdown(text, max_chunk_tokens=50, min_chunk_tokens=10)
    assert len(chunks) > 1
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_chunk_markdown_preserves_content():
    text = "First paragraph about liability.\n\nSecond paragraph about warranty."
    chunks = chunk_markdown(text, max_chunk_tokens=100)
    combined = " ".join(c.content for c in chunks)
    assert "liability" in combined
    assert "warranty" in combined


def test_estimate_tokens():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("hello") == 1
    assert estimate_tokens("a" * 40) == 10


def test_text_chunk_dataclass():
    chunk = TextChunk(content="test", chunk_index=0, page_number=1)
    assert chunk.content == "test"
    assert chunk.page_number == 1
    assert chunk.metadata == {}
