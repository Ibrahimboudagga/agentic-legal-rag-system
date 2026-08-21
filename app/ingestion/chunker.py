from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page_number: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    clause: str | None = None
    parent_id: str | None = None
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
    current_section: str | None = None
    current_clause: str | None = None
    current_page: int | None = None
    active_section: str | None = None
    active_clause: str | None = None
    active_page: int | None = None
    chunk_index = 0
    char_pos = 0

    for para in paragraphs:
        para_stripped = para.strip()
        if not para_stripped:
            char_pos += len(para) + 2  # account for \n\n
            continue

        section = _extract_section(para_stripped) or active_section
        clause = _extract_clause(para_stripped) or active_clause
        page = _extract_page_marker(para_stripped) or active_page

        if _extract_section(para_stripped):
            active_section = section
        if _extract_clause(para_stripped):
            active_clause = clause
        if _extract_page_marker(para_stripped):
            active_page = page

        para_tokens = len(para_stripped) // 4
        current_tokens = len(current_text) // 4 if current_text else 0

        if current_tokens + para_tokens > max_chunk_tokens and current_text:
            chunk_content = current_text.strip()
            if len(chunk_content) // 4 >= min_chunk_tokens:
                chunks.append(
                    TextChunk(
                        content=chunk_content,
                        chunk_index=chunk_index,
                        page_number=current_page,
                        page_start=current_page,
                        page_end=current_page,
                        section=current_section,
                        clause=current_clause,
                        parent_id=_build_parent_id(current_section, current_clause),
                        start_char=current_start,
                        end_char=char_pos,
                        metadata={
                            "section": current_section,
                            "clause": current_clause,
                            "page_start": current_page,
                            "page_end": current_page,
                        },
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
            current_section = section
            current_clause = clause
            current_page = page

        char_pos += len(para) + 2

    if current_text.strip():
        chunk_content = current_text.strip()
        if len(chunk_content) // 4 >= min_chunk_tokens or len(chunks) == 0:
            chunks.append(
                TextChunk(
                    content=chunk_content,
                    chunk_index=chunk_index,
                    page_number=current_page,
                    page_start=current_page,
                    page_end=current_page,
                    section=current_section,
                    clause=current_clause,
                    parent_id=_build_parent_id(current_section, current_clause),
                    start_char=current_start,
                    end_char=char_pos,
                    metadata={
                        "section": current_section,
                        "clause": current_clause,
                        "page_start": current_page,
                        "page_end": current_page,
                    },
                )
            )

    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i

    return chunks


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return max(1, len(text) // 4)


def _extract_section(text: str) -> str | None:
    heading = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", text)
    if heading:
        return heading.group(1).strip()

    numbered_heading = re.match(r"^\s*(?:section\s+)?(\d+(?:\.\d+)*)[.)]?\s+([A-Z][^\n]{2,120})$", text, re.IGNORECASE)
    if numbered_heading:
        return f"{numbered_heading.group(1)} {numbered_heading.group(2).strip()}"
    return None


def _extract_clause(text: str) -> str | None:
    match = re.match(r"^\s*(?:clause\s+)?(\d+(?:\.\d+)*)(?:[.)]|\s+-|\s+)", text, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_page_marker(text: str) -> int | None:
    match = re.search(r"(?:^|\b)page\s+(\d+)(?:\b|$)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _build_parent_id(section: str | None, clause: str | None) -> str | None:
    if not section and not clause:
        return None
    safe_section = re.sub(r"[^a-z0-9]+", "_", (section or "section").lower()).strip("_")
    safe_clause = re.sub(r"[^a-z0-9.]+", "_", (clause or "clause").lower()).strip("_")
    return f"{safe_section}:{safe_clause}"
