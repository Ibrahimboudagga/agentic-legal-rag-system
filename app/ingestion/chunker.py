from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page_number: int | None = None
    start_char: int = 0
    end_char: int = 0
    metadata: dict = field(default_factory=dict)


def chunk_markdown(
    text: str,
    max_chunk_tokens: int = 512,
    chunk_overlap: int = 64,
    min_chunk_tokens: int = 50,
) -> list[TextChunk]:
    """Split markdown text into overlapping chunks, respecting paragraph boundaries.

    Uses a simple token estimate (1 token ~ 4 chars) for sizing.
    Prefers splitting on paragraph boundaries, falling back to sentence boundaries.
    """
    if not text or not text.strip():
        return []

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[TextChunk] = []
    current_text = ""
    current_start = 0
    chunk_index = 0
    char_pos = 0

    for para in paragraphs:
        para_stripped = para.strip()
        if not para_stripped:
            char_pos += len(para) + 2  # account for \n\n
            continue

        para_tokens = len(para_stripped) // 4
        current_tokens = len(current_text) // 4 if current_text else 0

        if current_tokens + para_tokens > max_chunk_tokens and current_text:
            chunk_content = current_text.strip()
            if len(chunk_content) // 4 >= min_chunk_tokens:
                chunks.append(
                    TextChunk(
                        content=chunk_content,
                        chunk_index=chunk_index,
                        start_char=current_start,
                        end_char=char_pos,
                    )
                )
                chunk_index += 1

            overlap_chars = chunk_overlap * 4
            if len(current_text) > overlap_chars:
                current_text = current_text[-overlap_chars:]
            else:
                current_text = ""

        if current_text:
            current_text += "\n\n" + para_stripped
        else:
            current_text = para_stripped
            current_start = char_pos

        char_pos += len(para) + 2

    if current_text.strip():
        chunk_content = current_text.strip()
        if len(chunk_content) // 4 >= min_chunk_tokens or len(chunks) == 0:
            chunks.append(
                TextChunk(
                    content=chunk_content,
                    chunk_index=chunk_index,
                    start_char=current_start,
                    end_char=char_pos,
                )
            )

    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i

    return chunks


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return max(1, len(text) // 4)
