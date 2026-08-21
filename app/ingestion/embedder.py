from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Protocol

import numpy as np

from shared.config import get_rag_config


class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    async def embed_query(self, query: str) -> list[float]:
        ...


@lru_cache(maxsize=1)
def _get_model():
    """Lazy-load sentence-transformers model."""
    from sentence_transformers import SentenceTransformer

    model_name = get_rag_config().embedding_model
    return SentenceTransformer(model_name)


class SentenceTransformerEmbeddingProvider:
    """Async provider wrapper around the local sentence-transformers model."""

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        return await asyncio.to_thread(embed_texts, texts)

    async def embed_query(self, query: str) -> list[float]:
        import asyncio

        return await asyncio.to_thread(embed_query, query)


def get_embedding_dim() -> int:
    """Return the embedding dimension for the configured model."""
    return int(os.getenv("EMBEDDING_DIM", "384"))


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts and return as list of float vectors."""
    if not texts:
        return []
    model = _get_model()
    embeddings = model.encode(
        texts,
        show_progress_bar=False,
        normalize_embeddings=True,
        batch_size=32,
    )
    return embeddings.tolist()


def embed_query(query: str) -> List[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return SentenceTransformerEmbeddingProvider()
